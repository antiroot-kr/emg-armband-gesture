import time
import numpy as np
import pyqtgraph as pg

import config
from config import (
    get_ch_color, get_diag_directions, CH_OFFSET, NO_SIGNAL_VARIATION_RAW,
    FFT_WINDOW_SEC, FFT_SAMPLE_RATE_DEFAULT, FFT_MAX_HZ,
    FFT_APPLY_FILTER, FFT_FILTER_OUT_RANGES,
    FFT_Y_GAIN,
    RAW_LINE_DOWNSAMPLE,
    RAW_FILL_BARS,
)

try:
    from scipy.signal import butter, filtfilt
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def render(win):
    view_mode = getattr(win, "view_mode", "raw")
    if view_mode == "fft":
        # stacked_plots 인덱스는 _apply_fft()에서 뷰 전환 시 한 번만 설정하면 충분함
        # (매 프레임 다시 설정하면 불필요한 위젯 갱신이 반복됨)
        if win.visualization_enabled["line"]:
            update_fft_graph(win)
        if not win.is_running or win.sample_count == 0:
            return
        if win.visualization_enabled["diagonal"]:
            update_diag_vector(win)
        if win.visualization_enabled["power"]:
            update_power_info(win)
        return
    # Raw 모드
    if not win.is_running or win.sample_count == 0:
        return
    is_fill_mode = win.rb_fill.isChecked()
    ptr = _raw_display_ptr(win)
    unified_x = win.x_axis[ptr % win.max_display]
    if win.visualization_enabled["line"]:
        update_raw_graph(win, is_fill_mode, unified_x, ptr)
    if win.visualization_enabled["diagonal"]:
        update_diag_vector(win)
    if win.visualization_enabled["power"]:
        update_power_info(win)

LINE_HEIGHT_PX = 1.5  # Bar 모드 신호 없을 때 막대 기본 높이

# 필터 차수 (시간 영역 선필터용)
_FFT_FILTER_ORDER = 2


def _apply_time_domain_filter(samples: np.ndarray, fs: float, filter_ranges: list) -> np.ndarray:
    """시간 영역에서 지정 구간 제거. samples는 복사본으로 넣어도 됨 (in-place 수정)."""
    if not _HAS_SCIPY or not filter_ranges or len(samples) < 4:
        return samples
    x = samples.astype(float)
    nyq = fs / 2.0
    for (low_hz, high_hz) in filter_ranges:
        if high_hz <= 0 or high_hz >= nyq:
            continue
        try:
            if low_hz <= 0 or low_hz < 1.0:
                # 0~high_hz 제거 → 고역통과 (high_hz 위만 통과)
                b, a = butter(_FFT_FILTER_ORDER, high_hz, btype="high", fs=fs)
            else:
                # low_hz~high_hz 제거 → 밴드스탑
                b, a = butter(_FFT_FILTER_ORDER, [low_hz, high_hz], btype="bandstop", fs=fs)
            x = filtfilt(b, a, x)
        except Exception:
            continue
    return x


def update_fft_graph(win):
    # STOP 상태면 마지막 프레임 유지, 뷰(줌/팬)만 사용 가능하도록 아무것도 갱신하지 않음
    if not getattr(win, "is_running", True):
        return

    # 첫 샘플 도착 이후 전체 수신 개수의 평균으로 주파수 축을 계산한다 (BLE 연결 대기 시간 제외).
    first_sample_time = getattr(win, "first_sample_time", None)
    if win.sample_count > 0 and first_sample_time is not None:
        elapsed = time.time() - first_sample_time
        if elapsed >= 0.1:
            fs = win.sample_count / elapsed
        else:
            fs = FFT_SAMPLE_RATE_DEFAULT
    else:
        fs = FFT_SAMPLE_RATE_DEFAULT
    now = time.monotonic()

    # 나이퀴스트: 표시 상한 = min(측정 fs/2, FFT_MAX_HZ)
    max_freq = min(fs / 2.0, FFT_MAX_HZ)
    max_freq = max(max_freq, 1.0)  # 0이 되지 않도록

    y_max_fft = config.N_CH * CH_OFFSET + (1.5 * CH_OFFSET)
    # 깜빡임 방지: 같은 범위를 매 프레임 다시 적용하지 않는다.
    applied_axis_max = getattr(win, "_fft_applied_axis_max", None)
    axis_changed = (
        not getattr(win, "_fft_axes_initialized", False)
        or applied_axis_max is None
        or abs(max_freq - applied_axis_max) >= 1.0
    )
    if axis_changed:
        win.fft_plot.setXRange(0, max_freq, padding=0)
        vb = win.fft_plot.getViewBox()
        vb.setLimits(xMin=0, xMax=max_freq, yMin=0, yMax=y_max_fft, minYRange=50, maxYRange=y_max_fft)
        win.fft_plot.setYRange(0, y_max_fft, padding=0)
        win._fft_axes_initialized = True
        win._fft_applied_axis_max = max_freq
    win._fft_last_max_freq = max_freq
    if hasattr(win, "graph_panel_title_label") and win.graph_panel_title_label:
        header_text = f"FFT (Frequency)  fs≈{fs:.0f}Hz · 0–{max_freq:.0f}Hz"
        last_header_update = getattr(win, "_fft_last_header_update", 0.0)
        if (
            header_text != getattr(win, "_fft_last_header_text", None)
            and now - last_header_update >= 0.25
        ):
            win.graph_panel_title_label.setText(header_text)
            win._fft_last_header_text = header_text
            win._fft_last_header_update = now

    # 0.1초 분량 샘플 수 → 2의 거듭제곱으로 올림(ceil_pow2), 단 max_display 초과 시 캡
    n_fft = int(fs * FFT_WINDOW_SEC)
    n_fft = min(win.max_display, max(8, n_fft))
    n_fft = 1 << int(np.ceil(np.log2(n_fft)))
    n_fft = min(n_fft, win.max_display)

    for i in range(config.N_CH):
        # 수신 전이거나 데이터 부족 시 해당 채널만 빈 라인 (is_running은 위에서 이미 체크됨)
        # 주의: 링버퍼가 한 바퀴 다 돌면 ptr이 max_display→0으로 리셋되는데, 그 순간
        # is_buf_full=True라면 버퍼엔 이미 데이터가 가득 차 있으므로 blank 처리하면
        # 안 된다 (그렇게 하면 버퍼가 한 바퀴 돌 때마다 전체 채널이 깜빡이게 된다).
        # 진짜로 데이터가 하나도 없는 경우(세션 시작 직후)에만 blank 처리한다.
        if not win.is_buf_full and win.ptr < 2:
            win.fft_lines[i].setData([], [])
            continue
        if win.is_buf_full:
            idx = (win.ptr - n_fft + np.arange(n_fft)) % win.max_display
            samples = win.raw_np_buf[i, idx].astype(float)
        else:
            take = min(win.ptr, n_fft)
            take = int(2 ** int(np.log2(max(2, take))))
            samples = win.raw_np_buf[i, win.ptr - take : win.ptr].astype(float)

        if len(samples) < 2:
            win.fft_lines[i].setData([], [])
            continue

        # config에서 켜 둔 경우: 주파수 계산 전에 시간 영역 필터 적용 (0~5Hz, 50~60Hz 등)
        if FFT_APPLY_FILTER:
            samples = _apply_time_domain_filter(samples.copy(), fs, FFT_FILTER_OUT_RANGES)

        # DC 제거 + Hann 윈도우 후 FFT
        samples = samples - np.mean(samples)
        samples = samples * np.hanning(len(samples))

        spectrum = np.fft.rfft(samples)
        mag = np.abs(spectrum)
        freqs = np.fft.rfftfreq(len(samples), 1.0 / fs)

        mask = freqs <= max_freq
        freqs = freqs[mask]
        mag = mag[mask]
        # scipy 없이 필터 켠 경우만 주파수 영역에서 구간 0으로 (폴백)
        if FFT_APPLY_FILTER and not _HAS_SCIPY:
            for low_hz, high_hz in FFT_FILTER_OUT_RANGES:
                kill = (freqs >= low_hz) & (freqs <= high_hz)
                mag[kill] = 0.0
        if len(mag) == 0:
            win.fft_lines[i].setData([], [])
            continue

        # 선형 스케일: 샘플 수로만 나눈 뒤, FFT_Y_GAIN으로 전체 크기만 조정
        n_samp = len(samples)
        mag_scaled = (mag / (n_samp + 1e-12)) * FFT_Y_GAIN

        # 채널별 밴드(center = base_offset)를 기준으로 매핑 (클리핑 없이 그대로 표시)
        base_offset = (config.N_CH - 1 - i) * CH_OFFSET + (CH_OFFSET / 2)
        band_half = CH_OFFSET * 0.45
        y_fft = base_offset - band_half + mag_scaled * (2 * band_half)
        win.fft_lines[i].setData(freqs, y_fft)


CHUNK_SIZE = 30  # scripts/single_channel_view.py 전용 (대시보드 fill 모드는 RAW_FILL_BARS 사용)
gap_range = 5  # 버퍼가 찼을 때 쓰는 위치(ptr) 앞에서 비워 둘 막대 수


def _raw_display_ptr(win):
    """RAW 그래프를 그릴 때 쓸 ptr.

    BLE는 샘플을 20개씩 묶어 보내서, 마지막 패킷이 처리되는 순간 ptr가 곧바로 0으로
    돌아간다. 그 사이에 렌더가 끼지 못하면 그 바퀴는 커서가 끝까지 그려지지 않으므로,
    지난 프레임 이후 한 바퀴가 돌았으면 이번 한 프레임만 끝(max_display)까지 그린다.
    """
    last = getattr(win, "_raw_last_rendered_ptr", None)
    win._raw_last_rendered_ptr = win.ptr
    if win.is_buf_full and last is not None and win.ptr < last:
        return win.max_display
    return win.ptr


def update_raw_graph(win, is_fill_mode, unified_x, ptr):
    for i in range(config.N_CH):

        # 현재 Raw 스케일 범위 계산 
        data_range, allowed_half_height = win.scale_manager._data_range_and_half_height()
        max_bar_pixels = 2.0 * allowed_half_height
        half_range = max(data_range / 2.0, 1.0)

        base_offset = (config.N_CH - 1 - i) * CH_OFFSET + (CH_OFFSET / 2)

        # fill 모드: 버퍼를 RAW_FILL_BARS개 구간으로 겹치지 않게 나눠 구간마다 막대 하나
        # (막대 하나 = Visual Samples의 1/RAW_FILL_BARS, 높이 = 그 구간의 최대 - 최소)
        if is_fill_mode:
            win.past_lines[i].setVisible(False)
            win.raw_lines[i].setVisible(False)

            num_bars = min(RAW_FILL_BARS, win.max_display)
            edges = np.linspace(0, win.max_display, num_bars + 1).astype(int)
            starts, ends = edges[:-1], edges[1:]
            bar_spacing = win.max_display / num_bars
            bar_x = (starts + ends - 1) / 2.0

            row = win.raw_np_buf[i]
            seg_range = np.maximum.reduceat(row, starts) - np.minimum.reduceat(row, starts)
            ratio = np.minimum(seg_range / half_range, 1.0)
            display_heights = np.maximum(ratio * max_bar_pixels, LINE_HEIGHT_PX)
            display_heights[seg_range < NO_SIGNAL_VARIATION_RAW] = LINE_HEIGHT_PX

            if not win.is_buf_full:
                # 아직 다 안 채워진 구간은 비움 (빈 칸의 0이 섞이면 높이가 부풀려짐)
                display_heights[ends > ptr] = 0
            else:
                # 지금 쓰고 있는 위치(ptr)부터 gap_range개 막대를 비워 새 데이터/옛 데이터 경계 표시
                gap_bar = int(np.searchsorted(edges, ptr % win.max_display, side="right") - 1)
                for k in range(gap_range):
                    display_heights[(gap_bar + k) % num_bars] = 0

            win.bar_items[i].setOpts(
                x=bar_x,
                height=display_heights,
                y0=base_offset - (display_heights / 2),
                width=bar_spacing * 0.6,
            )
            win.bar_items[i].setVisible(True)

            # 커서 x: 마지막 샘플 위치(ptr 기준)
            last_x = win.x_axis[(ptr - 1) % win.max_display] if win.sample_count > 0 else unified_x
            win.cursor_rects[i].setData(pos=[(last_x, base_offset)])


        # line 모드
        else:
            win.bar_items[i].setVisible(False)

            # 링 버퍼가 안 찼을 때
            if not win.is_buf_full:
                win.past_lines[i].setData([], [])
                win.past_lines[i].setVisible(False)

                if ptr <= 0:
                    x, y = np.array([]), np.array([])

                # 0 ~ ptr 구간 좌표 (화면 표시용으로만 다운샘플링)
                else:
                    x = win.x_axis[: ptr : RAW_LINE_DOWNSAMPLE]
                    y = win.scale_manager.get_scaled_array(
                        i, win.raw_np_buf[i, : ptr : RAW_LINE_DOWNSAMPLE]
                    )

            # 링 버퍼 한 바퀴 이상: past(ptr~끝) + current(0~ptr)
            else:
                # ptr 이후 구간은 과거 데이터 (화면 표시용으로만 다운샘플링)
                x_past = win.x_axis[ptr :: RAW_LINE_DOWNSAMPLE]
                y_past = win.scale_manager.get_scaled_array(
                    i, win.raw_np_buf[i, ptr :: RAW_LINE_DOWNSAMPLE]
                )
                win.past_lines[i].setData(x_past, y_past)
                win.past_lines[i].setVisible(True)

                # 0 ~ ptr 구간은 현재 구간 (화면 표시용으로만 다운샘플링)
                if ptr <= 0:
                    x, y = np.array([]), np.array([])
                else:
                    x = win.x_axis[: ptr : RAW_LINE_DOWNSAMPLE]
                    y = win.scale_manager.get_scaled_array(
                        i, win.raw_np_buf[i, : ptr : RAW_LINE_DOWNSAMPLE]
                    )
            # 현재 구간 라인 표시
            win.raw_lines[i].setData(x, y)
            win.raw_lines[i].setVisible(True)


            # 커서 표시 (x, y 모두 마지막 샘플 = ptr 기준)
            if win.sample_count > 0:
                prev_idx = (ptr - 1) % win.max_display
                last_x = win.x_axis[prev_idx]
                y_cursor = win.scale_manager.get_scaled_array(
                    i, np.array([win.raw_np_buf[i, prev_idx]])
                )[0]
                win.cursor_rects[i].setData(pos=[(last_x, y_cursor)])
            else:
                win.cursor_rects[i].setData(pos=[])


def update_diag_vector(win):

    directions = get_diag_directions()
    DATA_LEN = 100

    for i in range(config.N_CH):
        if win.ptr >= DATA_LEN:
            diag_raw = win.raw_np_buf[i, win.ptr - DATA_LEN : win.ptr]
        
        # ptr이 DATA_LEN보다 작을 때 
        else:
            diag_raw = (
                # 버퍼가 한 바퀴 돈 경우에는 '뒤+앞'을 이어 붙임 
                np.concatenate(
                    [win.raw_np_buf[i, -DATA_LEN + win.ptr :], win.raw_np_buf[i, : win.ptr]]
                )
                if win.is_buf_full
                # 버퍼가 안찼으면 현재 데이터까지만 사용 
                else win.raw_np_buf[i, : win.ptr]
            )

        if diag_raw.size < 2:
            continue

        # ratio(강도) 및 파형 정규화 
        scaler = win.scale_manager.scalers[i]

        # 채널별 진폭을 0~1로 변환 
        ratio = win.scale_manager.get_vector_intensity(i, win.last_amp[i])
        
        # 신호 크기(정규화된 파형)
        denom = max(scaler.current_max - scaler.baseline, 30)
        wave = (diag_raw - scaler.baseline) / denom


        # 벡터 길이 val 계산 
        val = ratio * 1.4 * win.diag_plot_limit

        # 너무 짧으면 안그림 
        if val < 2.0:
            win.diag_lines[i].setData([], [])
            continue

        # 방향 벡터 & 수직 벡터 계산 
        dx, dy = directions[i]
        perp_x, perp_y = -dy, dx

        # 진행 거리 t (대각선 방향 진행 거리)
        t = np.linspace(0, val, len(diag_raw))

        # 물결의 흔들림 크기 
        wave_amp = 15 * ratio * (t / (val + 1e-6))
        
        # 최종 x, y 좌표 계산 (뻗는 방향 + 수직 방향)
        res_x = (t * dx) + (perp_x * wave * wave_amp)
        res_y = (t * dy) + (perp_y * wave * wave_amp)

        # 시작점 (원점)
        res_x[0], res_y[0] = 0, 0

        # 선 데이터 적용 
        win.diag_lines[i].setData(res_x, res_y)

        # 투명도 
        color = pg.mkColor(get_ch_color(i))
        color.setAlpha(int(np.clip(80 + (ratio * 175), 80, 255)))

        # 선 굵기 
        win.diag_lines[i].setPen(pg.mkPen(color=color, width=1.5 + (ratio * 3.0)))


# PWR 그래프 막대 높이 갱신 
def update_power_info(win):

    ratios = np.array([
        win.scale_manager.get_vector_intensity(i, win.last_amp[i])
        for i in range(config.N_CH)
    ])
    height_pct = np.clip(ratios * 100.0, 0, 100)
    avg_pct = float(np.clip(np.mean(ratios) * 100.0, 0, 100))
    win.bar_item.setOpts(height=list(height_pct) + [avg_pct])
