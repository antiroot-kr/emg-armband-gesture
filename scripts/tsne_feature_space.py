"""
scripts/tsne_feature_space.py
==============================
132차원 feature 공간(firmware N_FEATURES와 동일)에서 6클래스(rest/flexion/
extension/close/supination/pronation)가 실제로 얼마나 겹치는지 t-SNE(+PCA
비교)로 시각화한다.

왜 오프라인(녹화된 데이터) 기반인가:
t-SNE는 전체 데이터셋을 한 번에 놓고 서로 간 거리를 계산하는 배치 알고리즘이라
실시간 스트리밍에 맞지 않는다. 게다가 t-SNE 임베딩은 실행할 때마다 좌표축
자체가 바뀌어서(회전/반사 불변성 없음) 이전 프레임의 위치와 비교할 수도 없다.
그래서 녹화된 세션 데이터(data/<subject>_BATCH*/*.csv)를 모아 firmware와
동일한 전처리+feature 파이프라인(lib/)으로 132차원을 뽑은 뒤, 그 스냅샷에
대해 한 번 계산하는 게 맞는 방식이다.

사용법 (mandro-pc-app 루트에서):
    .venv/Scripts/python.exe scripts/tsne_feature_space.py S006
    (특정 폴더만 보고 싶으면 EMG_DATA_SESSIONS="data/S006_BATCH1:data/S006_BATCH2"
    처럼 os.pathsep으로 구분해서 환경변수로 지정 — configs.py의 다른 스크립트와
    동일한 규칙)
"""
import glob
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

from lib.data_loader import load_datasets_new_format
from lib.pipeline import preprocess_pipeline, extract_features_pipeline
from lib.windowing import get_windows, get_action_windows
from lib.configs import (
    LABELS, SAMPLING_FREQ, WINDOW_SIZE, LOWCUT, HIGHCUT, DELAY_S, KERNEL_RATIO,
    TSD_WIN_MS, TSD_INC_MS, TSD_LAM, GESTURE_SETS, ROOT_DIR,
)

ACTIONS = {g: i for i, g in enumerate(GESTURE_SETS["6cl"])}
IDX2NAME = {v: k for k, v in ACTIONS.items()}
COLORS = {
    "rest": "#9e9e9e", "flexion": "#1f77b4", "extension": "#ff7f0e",
    "close": "#d62728", "supination": "#2ca02c", "pronation": "#9467bd",
}


def discover_sessions(subject, data_root):
    override = os.environ.get("EMG_DATA_SESSIONS")
    if override:
        return [os.path.normpath(d.strip()) for d in override.split(os.pathsep) if d.strip()]
    return sorted(
        d for d in glob.glob(os.path.join(data_root, f"{subject}_BATCH*"))
        if re.match(rf"^{re.escape(subject)}_BATCH\d+$", os.path.basename(d))
        and os.path.isdir(d)
    )


def preprocess_one(df):
    return preprocess_pipeline(
        df, labels=LABELS, sampling_frequency_EMG=SAMPLING_FREQ,
        lowcut=LOWCUT, highcut=HIGHCUT, delay_s=DELAY_S,
        kernel_ratio=KERNEL_RATIO, window_size=WINDOW_SIZE, warmup_samples=100,
    )


def take_to_arrays(df):
    X_list, y_list = [], []
    for w in get_windows(df, WINDOW_SIZE):
        if (w['Action'] == -1).any():   # pause 등 미매핑 라벨 섞인 창은 제외
            continue
        X_list.append(w[LABELS].values)
        y_list.append(get_action_windows(w))
    if not X_list:
        return np.empty((0,)), np.empty((0,))
    return np.array(X_list), np.array(y_list)


def main():
    subject = sys.argv[1] if len(sys.argv) > 1 else "S006"
    data_root = os.path.join(ROOT_DIR, "data")
    session_dirs = discover_sessions(subject, data_root)
    if not session_dirs:
        raise SystemExit(f"'{subject}_BATCH*' 폴더를 못 찾음: {data_root}")
    print(f"세션: {[os.path.basename(d) for d in session_dirs]}")

    X_raw_all, y_all = [], []
    for d in session_dirs:
        for df in load_datasets_new_format(d, ACTIONS, LABELS):
            Xr, y = take_to_arrays(preprocess_one(df))
            if len(Xr):
                X_raw_all.append(Xr)
                y_all.append(y)

    if not X_raw_all:
        raise SystemExit("유효한 윈도우를 하나도 못 뽑음 — 세션 폴더/라벨 확인 필요")

    X_raw = np.concatenate(X_raw_all)      # (n_windows, 128, 8)
    y = np.concatenate(y_all)              # class index
    print(f"총 {len(y)}개 윈도우, 클래스 분포: "
          + ", ".join(f"{IDX2NAME[i]}={int(np.sum(y == i))}" for i in range(len(ACTIONS))))

    X_feat = extract_features_pipeline(
        X_raw, SAMPLING_FREQ, mode="concat",
        tsd_win_ms=TSD_WIN_MS, tsd_inc_ms=TSD_INC_MS, tsd_lam=TSD_LAM,
    )
    print(f"feature shape: {X_feat.shape}  (firmware N_FEATURES=132와 일치해야 함)")

    Xs = StandardScaler().fit_transform(X_feat)

    print("PCA 계산 중...")
    pca_proj = PCA(n_components=2, random_state=42).fit_transform(Xs)

    print("t-SNE 계산 중... (데이터 많으면 수십 초~수 분 걸릴 수 있음)")
    tsne_proj = TSNE(n_components=2, perplexity=30, random_state=42, init="pca").fit_transform(Xs)

    _, axes = plt.subplots(1, 2, figsize=(15, 7))
    for ax, proj, title in zip(axes, [pca_proj, tsne_proj], ["PCA", "t-SNE"]):
        for idx, name in IDX2NAME.items():
            m = y == idx
            if not m.any():
                continue
            ax.scatter(proj[m, 0], proj[m, 1], s=12, alpha=0.6,
                       label=f"{name} (n={int(m.sum())})", color=COLORS.get(name))
        ax.set_title(f"{title} — 132차원 feature 공간 ({subject})")
        ax.legend(markerscale=2, fontsize=8)
    plt.tight_layout()

    out_dir = os.path.join(ROOT_DIR, "results")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"tsne_{subject}.png")
    plt.savefig(out_path, dpi=150)
    print(f"저장됨: {out_path}")
    plt.show()


if __name__ == "__main__":
    main()
