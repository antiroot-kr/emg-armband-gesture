# 개발자 가이드

이 프로젝트를 유지 보수하거나 기능을 추가할 사람을 위한 문서입니다.
설치는 [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md), 전체 소개는 [README.md](../README.md)를 보세요.

---

## 1. 전체 구조

ESP32-S3 팔찌에서 8채널 근전도를 BLE로 받아 녹화하고, **피험자마다** 손동작 분류 모델을
학습시킨 뒤, 팔찌 안에서 실시간으로 추론합니다. PyQt6 데스크톱 앱이 Phase 0 → 5 순서로
작업을 안내합니다.

### 폴더 구성

| 경로 | 내용 |
|---|---|
| [client_app/](../client_app/) | PyQt6 앱 |
| ├ [main.py](../client_app/main.py) | 시작 파일 |
| ├ `phase0_install_capture.py`, `phase2_training.py`, `phase3_install.py`, `phase4_verify.py`, `phase5_online_score.py` | Phase별 화면 |
| ├ [app_window.py](../client_app/app_window.py) | 메인 창. 녹화 순서, 동작 안내, 신호 품질 경고 |
| ├ [dashboard_ui.py](../client_app/dashboard_ui.py) | 실시간 신호 대시보드 |
| ├ [serial_worker.py](../client_app/serial_worker.py) | BLE 수신 스레드 (약 1200Hz) |
| ├ [logger.py](../client_app/logger.py) | 녹화 CSV 저장 |
| ├ [protocol_controller.py](../client_app/protocol_controller.py) | 녹화 순서(쉬기 5초 / 동작 10초)와 라벨 |
| ├ `take_viewer.py`, `view_single_take.py` | 녹화 결과 보기 |
| └ `subjects_registry.py`, `sessions_registry.py` | 피험자·세션 기록 |
| [lib/](../lib/) | 데이터 처리와 학습 |
| ├ `data_loader.py`, `preprocessing.py`, `features/`, `windowing.py`, `pipeline.py` | 불러오기, 전처리, 윈도우, feature |
| ├ `models.py`, `training.py`, `evaluation.py`, `export.py` | 모델 구성, 학습, 평가, 내보내기 |
| ├ [configs.py](../lib/configs.py) | 공통 설정값 |
| ├ [firmware_uploader.py](../lib/firmware_uploader.py) | `arduino-cli`로 펌웨어 컴파일·업로드, USB 포트 찾기 |
| └ [ble_weights.py](../lib/ble_weights.py) | 모델 가중치를 BLE로 팔찌에 전송 |
| [scripts/](../scripts/) | 앱 없이 실행하는 도구 |
| ├ [train_causal_concat.py](../scripts/train_causal_concat.py) | Phase 2에서 앱이 실행하는 학습 스크립트 |
| ├ [train_multisession.py](../scripts/train_multisession.py) | 세션 단위 검증(LOSO / GroupKFold) + 최종 모델 학습 |
| └ `benchmark_offline.py`, `capture_live_predictions.py`, `export_teensy_headers.py`, `single_channel_view.py`, `tsne_feature_space.py` | 평가, 실시간 예측 기록, 헤더 내보내기, 그래프 성능 실험, feature 시각화 |
| [firmware/esp32/exo_armband_hybrid_6clf/](../firmware/esp32/exo_armband_hybrid_6clf/exo_armband_hybrid/) | 현재 팔찌 펌웨어 (4절) |
| `data/`, `models/` | 녹화 데이터, 학습한 모델 |

### 주요 식별값

| 항목 | 값 |
|---|---|
| BLE 기기 이름 | `ESP32S3_FAST_BLE` |
| 보드 FQBN | `esp32:esp32:esp32s3` |
| Python | 3.10 이상 (`X \| None` 타입 표기를 써서 3.9에서는 실행 중 멈춤), Windows는 3.12 권장 |

---

## 2. 개발 환경

설치 절차는 [INSTALLATION_GUIDE.md](INSTALLATION_GUIDE.md)와 같습니다. 요약하면:

```powershell
.\setup.bat                                   # 가상환경 + requirements.txt 설치
.venv\Scripts\python.exe client_app\main.py   # 실행
```

패키지 버전은 [requirements.txt](../requirements.txt)에 고정되어 있습니다. 저장해 둔 scaler(`.pkl`)는
만들 때와 다른 scikit-learn 버전으로 불러오면 버전 경고가 날 수 있으니, 고정된 버전을 그대로 쓰세요.

---

## 3. 데이터 처리 흐름

설정값([lib/configs.py](../lib/configs.py)): 샘플링 **1200Hz**, 윈도우 **128샘플**(약 107ms),
**8채널**, 대역 통과 필터 **35~300Hz**, 손동작 **6가지**(rest, flexion, extension, close,
supination, pronation).

### CSV 형식 (녹화 한 번당 파일 한 개)

```
Time(ms), Raw_CH0..Raw_CH7, Amp_CH0..Amp_CH7, Label, Window
```

학습에는 `Raw_CH*`를 대역 통과 필터로 거른 값을 씁니다.

### 단계

| 순서 | 단계 | 함수 |
|---|---|---|
| 1 | 불러오기 | `data_loader.load_datasets_new_format` |
| 2 | 전처리 (대역 통과 필터 등) | `pipeline.preprocess_pipeline` |
| 3 | 윈도우 나누기 — 겹치지 않는 128샘플 블록, 라벨은 다수결 | `windowing.get_windows`, `get_action_windows` |
| 4 | feature 추출 — `concat` 모드(기본 feature + TSD feature, 132차원) | `pipeline.extract_features_pipeline` |
| 5 | 표준화 — 학습 데이터로만 scaler를 맞춤 | `pipeline.fit_scaler` |
| 6 | 모델 구성 — 은닉층 2개, 64 유닛, lr 0.001 | `models.build_model` |
| 7 | 학습 | `training.train_model` |

---

## 4. 펌웨어

앱이 빌드하는 스케치는 [firmware/esp32/exo_armband_hybrid_6clf/exo_armband_hybrid/](../firmware/esp32/exo_armband_hybrid_6clf/exo_armband_hybrid/) 하나입니다.

- raw 근전도는 모델 유무와 관계없이 항상 BLE로 보냅니다.
- 추론은 `nn.isLoaded()`가 참일 때만 합니다. 가중치는 BLE로 받아 팔찌 저장소(LittleFS)의
  `/weights.bin`에 저장하고, 부팅할 때 불러옵니다([lib/ble_weights.py](../lib/ble_weights.py)).
- Phase 0("Install capture firmware")과 Phase 3("Install on bracelet")은 둘 다 이 스케치를
  올립니다(`lib/firmware_uploader.py`의 `install_raw_firmware()`, `upload_model()`).

| 파일 | 내용 |
|---|---|
| `exo_armband_hybrid.ino` | 메인 코드: 센서 읽기, BLE 전송, 추론 호출, 의수(MARK7) 연결 |
| `preprocessor.cpp/h` | 필터와 feature(132차원) 계산 |
| `nn.cpp/h` | 신경망 계산 |
| `MODEL.h` | 모델 구조(층 크기, 활성화 함수) |

`firmware/esp32/`의 `exo_armband_raw/`(녹화 전용)와 `exo_armband_hybrid_4clf_USBSERIAL/`(4클래스,
USB 시리얼 출력)은 예전 펌웨어입니다. 앱은 쓰지 않습니다.

컴파일만 확인하기 (업로드 없음):

```bash
arduino-cli compile --fqbn esp32:esp32:esp32s3 firmware/esp32/exo_armband_hybrid_6clf/exo_armband_hybrid
```

---

## 5. 학습과 정확도 평가

Phase 2는 [scripts/train_causal_concat.py](../scripts/train_causal_concat.py)를 실행합니다.

- 학습 데이터(`EMG_DATA_RAW`)와 테스트 데이터(`EMG_DATA_TEST_RAW`) 경로를 환경 변수로 받습니다.
- 학습 데이터 안에서 윈도우를 **무작위로 섞어** 학습용과 검증용으로 나눕니다(`split_train_val`).
  붙어 있는 윈도우가 양쪽에 들어가서 **검증 정확도가 실제보다 높게 나옵니다.**
- 실제 사용에 가까운 정확도는 다른 세션으로 측정한 **테스트 정확도**입니다.

실제 성능을 보려면 [scripts/train_multisession.py](../scripts/train_multisession.py)를 쓰세요.

- 피험자의 세션 폴더(`<피험자>_BATCH<N>`)를 자동으로 모두 찾습니다.
- 세션이 2개 이상이면 **Leave-One-Session-Out** 교차 검증(세션 하나씩 빼고 검증)을 합니다.
- 세션이 1개면 **녹화(take) 단위 GroupKFold**로 대신하고, 이 값은 실사용 성능이 아니라고 경고합니다.
- 특정 세션만 쓰려면 `EMG_DATA_SESSIONS`, 배포 중인 모델을 덮어쓰지 않으려면 `EMG_MODEL_OUTPUT_NAME`을 지정합니다.

---

## 6. 모델 파일

| 파일 | 위치 | 이름 형식 |
|---|---|---|
| 모델 | `models/trained/*.keras` | `model_<피험자>_<N>cl_<날짜>[...].keras` |
| scaler | `models/scalers/*.pkl` | 모델 이름과 같은 규칙 |

---

## 7. 자주 하는 작업

| 작업 | 방법 |
|---|---|
| 새 피험자 녹화와 학습 | 앱을 실행해 Phase 0 → 3 진행 |
| 앱 없이 다시 학습 | `EMG_DATA_RAW`, `EMG_DATA_TEST_RAW`를 지정하고 `python scripts/train_causal_concat.py`, 또는 `train_multisession.py` |
| 펌웨어 신호 설정 바꾸기 | `exo_armband_hybrid.ino`에서 `analogReadResolution(...)`, `tmp -= ...` 오프셋, `sensorPin[]`을 고친 뒤 다시 업로드 |
| 손동작 종류 추가 | 아래 참고 |

### 손동작을 추가할 때 고칠 곳

코드에서 손동작 목록이 정의된 곳입니다. 실제로 추가해 본 적은 없으니 진행하면서 확인하세요.

1. [lib/configs.py](../lib/configs.py)의 `GESTURE_SETS`
2. [client_app/protocol_controller.py](../client_app/protocol_controller.py)의 `GESTURES_BY_N_CLASSES`
3. `client_app/assets/gestures/`에 안내 그림과 애니메이션 프레임 추가
4. 펌웨어의 `N_CLASSES`, `CLASS_NAMES`(`exo_armband_hybrid.ino`)와 `MODEL.h`의 출력층 크기
5. 다시 녹화하고 학습

---

## 8. 알려진 한계

- **`EMG_DATA_TEST_RAW`를 지정하지 않으면 기본값(S003 데이터)으로 테스트합니다.** 경고 없이
  다른 피험자로 평가되므로 항상 직접 지정하세요. 값이 없을 때 오류를 내도록 고치는 것을 권장합니다.
- `train_multisession.py`의 각 교차 검증 단계 안에서도 early stopping용 검증 데이터는 윈도우를
  무작위로 섞어 나눕니다(`split_train_val`). 보고하는 정확도를 부풀리지는 않지만 완전히 깔끔하지는 않습니다.
- `scripts/benchmark_offline.py`도 같은 무작위 분할을 씁니다. 결과를 믿기 전에 확인하세요.
- BLE 수신 속도는 환경에 따라 목표(1200Hz)보다 낮아질 수 있고, 연결이 끊겨도 녹화 순서는 계속
  진행됩니다. 앱을 실행한 터미널의 `[BLE] ... Hz` 줄로 확인하세요.

---

## 9. 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 실시간 인식이 엉망이다 | 팔찌에 최신 펌웨어가 올라가 있는지, 전극 접촉, 모델이 실렸는지(부팅 때 시리얼 로그에 `/weights.bin` 로드 여부가 찍힘) |
| 앱 경고 "electrode contact" | 채널 하나가 평평하거나 죽어 있음 → 팔찌를 다시 차기 |
| 앱 경고 "weak / old firmware" | 예전 8-bit 펌웨어로 녹화된 데이터 → Phase 0에서 펌웨어 다시 설치 |
| scaler 버전 경고 | `requirements.txt`에 고정된 scikit-learn 버전을 쓰고 있는지 확인 |
| arduino-cli: core not installed | `arduino-cli core install esp32:esp32` |
