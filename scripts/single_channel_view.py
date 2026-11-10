"""
scripts/single_channel_view.py
================================
링버퍼/그리기 성능 비교실험용 — dashboard_ui.py의 RAW 뷰(Line/Fill 전환)를
재현하되, 채널별로 "연산"과 "그리기"를 독립적으로 켜고 끌 수 있게 만든 스크립트.

체크박스 2종류 (채널마다 각각):
  - 연산(compute): on_sample()에서 이 채널의 오토스케일(ChannelScaler.update,
    min/max/baseline 갱신)을 할지 말지 결정. 링버퍼 쓰기는 이 체크와 무관하게
    항상 수행된다 — 즉 데이터 자체는 안 끊기고, "오토스케일 계산만" on/off됨.
  - 그리기(draw): render()에서 이 채널의 chunk 통계 계산 + setData 호출을
    할지 말지 결정. 꺼지면 계산 자체를 건너뛰고 화면에서도 숨겨진다
    (기존처럼 "계산은 다 하고 숨기기만" 하는 게 아니라 진짜로 스킵함).

이 둘을 독립적으로 조합하면:
  - 연산 ON + 그리기 ON  : 원본과 동일한 상태
  - 연산 ON + 그리기 OFF : 오토스케일은 계속 반영되지만(공유 data_range에 계속
                            영향을 줌) 화면에는 안 그려짐 → "그리기 부하"만 측정
  - 연산 OFF + 그리기 ON : 그 채널의 오토스케일만 멈춰서 공유 data_range에 더는
                            영향을 안 주지만, 데이터/그리기는 그대로 계속됨
                            → "오토스케일이 튐 현상에 미치는 영향"만 측정
  - 연산 OFF + 그리기 OFF: 오토스케일도 안 하고 화면에도 안 그림

render()는 client_app/graph_render.py의 update_raw_graph()를 더 이상 그대로
호출하지 않는다 — 그 함수는 채널 스킵 개념이 없어서 "그리기 OFF"를 계산
자체를 건너뛰는 방식으로 구현할 수 없기 때문. 대신 그 함수와 동일한 로직을
로컬로 복사하되, 그리기 OFF인 채널은 아예 처리하지 않도록 앞에서 걸러낸다.
그리기 ON인 채널의 렌더링 결과는 원본과 100% 동일하다.

BLE 수신 경로(serial_worker.py의 SerialWorker)는 대시보드와 동일하게 재사용한다.
체크박스 상태와 무관하게 BLE 워커는 항상 8채널 전체 데이터를 GUI 스레드로
넘기며, 필터링은 GUI 스레드의 on_sample()/render() 안에서만 일어난다.

사용법:
    .venv/Scripts/python.exe scripts/single_channel_view.py
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "client_app"))

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QCheckBox, QRadioButton, QButtonGroup, QLabel, QPushButton,
)

import config
from config import get_ch_color
from emg_scale import EMGScaleManager
from graph_render import CHUNK_SIZE, gap_range, LINE_HEIGHT_PX
from serial_worker import SerialWorker

# QSS의 image: url(data:...)는 Qt에서 안정적으로 렌더링되지 않아(빈 화면),
# 체크마크(✓) PNG를 실제 파일로 저장해두고 그 파일 경로를 QSS에서 참조한다.
_ICON_DIR = Path(tempfile.mkdtemp(prefix="emg_channel_view_icons_"))


def _checkmark_icon_path(color: str, size: int = 16) -> str:
    """체크됨 상태에 보일 체크마크(✓)를 QPainter로 그려 PNG 파일로 저장하고
    그 경로를 반환한다(같은 color+size는 캐시된 파일을 재사용)."""
    safe_name = color.lstrip("#")
    path = _ICON_DIR / f"check_{safe_name}_{size}.png"
    if path.exists():
        return path.as_posix()

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(max(size * 0.16, 1.5))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    m = size * 0.2
    p1 = QPointF(m, size * 0.55)
    p2 = QPointF(size * 0.42, size - m)
    p3 = QPointF(size - m, m)
    painter.drawLine(p1, p2)
    painter.drawLine(p2, p3)
    painter.end()

    pixmap.save(str(path), "PNG")
    return path.as_posix()


def _channel_checkbox_style(color: str, size: int) -> str:
    """체크 안 됨 = 어두운 빈 박스 + 채널색 테두리, 체크됨 = 흰 배경 +
    채널색 체크마크(✓). 색만 채우는 게 아니라 진짜 체크박스처럼 보이게 함."""
    return f"""
        QCheckBox::indicator {{
            width: {size}px; height: {size}px;
            border: 2px solid {color};
            border-radius: 3px;
            background: #1a2138;
        }}
        QCheckBox::indicator:checked {{
            background: #ffffff;
            border: 2px solid {color};
            image: url({_checkmark_icon_path(color, size)});
        }}
        QCheckBox::indicator:hover {{
            border: 2px solid #ffffff;
        }}
    """


class MultiChannelView(QMainWindow):
    def __init__(self):
        super().__init__()
        pg.setConfigOptions(antialias=True, useOpenGL=False)  # dashboard_ui.py와 동일

        self.setWindowTitle("Multi Channel Raw View (연산/그리기 개별 on-off 실험)")
        self.resize(1500, 700)

        central = QWidget()
        central.setStyleSheet(f"background-color: {config.COLOR_BG};")
        outer = QVBoxLayout(central)
        self._checkbox_size = 16

        # 헤더: 제목 + Line/Fill
        header = QHBoxLayout()
        title = QLabel("RAW GRAPH (Dynamic Auto-Scaling)")
        title.setStyleSheet("font-size: 14px; font-weight: 800; color: #9fb3ff;")
        header.addWidget(title)
        header.addStretch(1)

        self.rb_line = QRadioButton("Line")
        self.rb_fill = QRadioButton("Fill")
        self.rb_line.setChecked(True)
        for rb in (self.rb_line, self.rb_fill):
            rb.setStyleSheet("color: white; font-weight: bold;")
        self.bg_display = QButtonGroup(self)
        self.bg_display.addButton(self.rb_line)
        self.bg_display.addButton(self.rb_fill)
        header.addWidget(self.rb_line)
        header.addWidget(self.rb_fill)

        outer.addLayout(header)

        # 그래프 바로 위: 연산 전체선택 / 그리기 전체선택 (중립색 체크마크)
        neutral_style = _channel_checkbox_style("#9fb3ff", self._checkbox_size)
        select_all_row = QHBoxLayout()
        self.cb_compute_all = QCheckBox("AutoScale 전체 선택")
        self.cb_draw_all = QCheckBox("그리기 전체 선택")
        for cb in (self.cb_compute_all, self.cb_draw_all):
            cb.setChecked(True)
            cb.setStyleSheet(neutral_style + "QCheckBox { color: white; font-weight: bold; }")
        self.cb_compute_all.toggled.connect(self._on_compute_all_toggled)
        self.cb_draw_all.toggled.connect(self._on_draw_all_toggled)
        select_all_row.addWidget(self.cb_compute_all)
        select_all_row.addWidget(self.cb_draw_all)
        select_all_row.addStretch(1)

        # 수동 버퍼 리사이즈 버튼 — 누를 때마다 그 시점까지의 누적 평균
        # rate로 즉시 1회 리사이즈. 자동(START 5초 시점 1회)과는 별개로,
        # 언제든 몇 번이든 다시 누를 수 있다.
        self.btn_resize = QPushButton("버퍼 리사이즈")
        self.btn_resize.setStyleSheet(
            "QPushButton { background:#1a2138; color:white; border:1px solid #5a6690;"
            " border-radius:4px; padding:3px 10px; font-weight:bold; }"
            "QPushButton:hover { border:1px solid #9fb3ff; }"
            "QPushButton:pressed { background:#2a3550; }"
        )
        self.btn_resize.clicked.connect(self._on_resize_button_clicked)
        select_all_row.addWidget(self.btn_resize)

        outer.addLayout(select_all_row)

        # 채널별 [AutoScale][그리기][CH라벨] 체크박스 — plot 왼쪽의 별도 영역
        # (checkbox_area)에 절대좌표로 배치한다. QGridLayout의 행 stretch가
        # 의도대로 안 퍼져서(다 밑에 뭉침), 대신 plot의 실제 채널 band 위치를
        # 뷰→화면 좌표로 직접 계산해서 그 y좌표에 맞춰 넣는다. plot_widget과
        # 같은 QHBoxLayout 행에서 위쪽이 정렬되므로 y좌표를 그대로 재사용 가능.
        self.active = [True] * config.N_CH        # AutoScale 연산 on/off
        self.draw_active = [True] * config.N_CH    # 그리기 on/off
        self.compute_checks = []
        self.draw_checks = []
        self.ch_labels = []

        self.checkbox_area = QWidget()
        self.checkbox_area.setMinimumWidth(150)

        col_compute = QLabel("AutoScale", self.checkbox_area)
        col_draw = QLabel("그리기", self.checkbox_area)
        for lbl in (col_compute, col_draw):
            lbl.setStyleSheet("color: #9fb3ff; font-size: 11px; font-weight: bold;")
        col_compute.move(8, 4)
        col_draw.move(8 + self._checkbox_size + 8, 4)

        for i in range(config.N_CH):
            color = get_ch_color(i)
            style = _channel_checkbox_style(color, self._checkbox_size)

            cb_compute = QCheckBox(self.checkbox_area)
            cb_compute.setChecked(True)
            cb_compute.setToolTip(f"CH{i} AutoScale 연산 여부")
            cb_compute.setStyleSheet(style)
            cb_compute.toggled.connect(lambda checked, idx=i: self._on_compute_toggled(idx, checked))
            self.compute_checks.append(cb_compute)

            cb_draw = QCheckBox(self.checkbox_area)
            cb_draw.setChecked(True)
            cb_draw.setToolTip(f"CH{i} 그리기")
            cb_draw.setStyleSheet(style)
            cb_draw.toggled.connect(lambda checked, idx=i: self._on_draw_toggled(idx, checked))
            self.draw_checks.append(cb_draw)

            ch_label = QLabel(f"CH{i}", self.checkbox_area)
            ch_label.setStyleSheet(f"color: {color}; font-weight: bold;")
            self.ch_labels.append(ch_label)

        # dashboard_ui.py의 raw_plot 설정과 동일
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground(config.COLOR_BG)
        self.plot_widget.hideButtons()
        self.plot_widget.getAxis("left").setStyle(showValues=False)
        self.plot_widget.getAxis("bottom").enableAutoSIPrefix(False)

        x_max_ms = config.PLOT_SEC * 1000
        y_max = config.N_CH * config.CH_OFFSET

        self.plot_widget.setXRange(0, x_max_ms, padding=0)
        self.plot_widget.setLabel("bottom", "Time", units="ms")
        self.plot_widget.setYRange(0, y_max, padding=0)

        vb = self.plot_widget.getViewBox()
        vb.setLimits(
            xMin=0, xMax=x_max_ms,
            minXRange=200, maxXRange=x_max_ms,
            yMin=0, yMax=y_max,
            minYRange=50, maxYRange=y_max,
        )
        self.plot_widget.setMouseEnabled(x=True, y=True)

        body = QHBoxLayout()
        body.setSpacing(10)
        body.addWidget(self.checkbox_area)
        body.addWidget(self.plot_widget, 1)

        outer.addLayout(body, 1)
        self.setCentralWidget(central)

        # 채널별 라인/바/커서 아이템 (dashboard_ui.py init_ui()와 동일)
        self.past_lines = []
        self.raw_lines = []
        self.bar_items = []
        self.cursor_rects = []
        for i in range(config.N_CH):
            past_line = self.plot_widget.plot(
                [], [], pen=pg.mkPen(color=get_ch_color(i), width=config.RAW_LINE_WIDTH, alpha=0.6)
            )
            self.past_lines.append(past_line)

            line = self.plot_widget.plot(
                [], [], pen=pg.mkPen(color=get_ch_color(i), width=config.RAW_LINE_WIDTH)
            )
            self.raw_lines.append(line)

            bar = pg.BarGraphItem(
                x=[], height=[], width=20.0,
                brush=pg.mkBrush(get_ch_color(i)), pen=None,
            )
            self.plot_widget.addItem(bar)
            bar.setVisible(False)
            self.bar_items.append(bar)

            rect = pg.ScatterPlotItem(size=8, symbol="s", brush="#ffffff")
            self.plot_widget.addItem(rect)
            self.cursor_rects.append(rect)

        # 링버퍼: dashboard_ui.py와 동일한 초기 크기 산정 방식 (8채널 전부)
        self.max_display = max(
            config.MIN_BUF,
            min(config.MAX_BUF, int(round(config.RAW_SAMPLE_RATE_DEFAULT * config.PLOT_SEC))),
        )
        self.raw_np_buf = np.zeros((config.N_CH, self.max_display))
        self.height_buf = np.zeros((config.N_CH, self.max_display))
        self.height_buf.fill(1.5)
        self.x_axis = np.linspace(0, config.PLOT_SEC * 1000, self.max_display)
        self.ptr = 0
        self.is_buf_full = False
        self.sample_count = 0
        self._has_resized_once = False
        self.start_time_ref = None

        self.scale_manager = EMGScaleManager()

        self.worker = SerialWorker()
        self.worker.sig_sample.connect(self.on_sample)
        self.worker.sig_status.connect(lambda s: print(f"[status] {s}"))
        self.worker.sig_error.connect(lambda e: print(f"[error] {e}"))

        # 그리기는 dashboard_ui.py와 동일하게 수신과 분리된 고정 FPS 타이머로 처리
        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / config.FPS))
        self.timer.timeout.connect(self.render)
        self.timer.start()

    def start(self):
        self.start_time_ref = time.time()
        self.worker.start()

    # ── 연산(compute) on/off ────────────────────────────────────────
    def _on_compute_toggled(self, idx: int, checked: bool):
        self.active[idx] = checked

    def _on_compute_all_toggled(self, checked: bool):
        for cb in self.compute_checks:
            cb.setChecked(checked)

    # ── 그리기(draw) on/off ─────────────────────────────────────────
    def _on_draw_toggled(self, idx: int, checked: bool):
        self.draw_active[idx] = checked
        if not checked:
            # 꺼지는 즉시 화면에서도 숨김 (다음 render tick까지 기다리지 않음)
            self.past_lines[idx].setData([], [])
            self.raw_lines[idx].setData([], [])
            self.bar_items[idx].setVisible(False)
            self.cursor_rects[idx].setData(pos=[])

    def _on_draw_all_toggled(self, checked: bool):
        for cb in self.draw_checks:
            cb.setChecked(checked)

    def _reposition_channel_checkboxes(self):
        """각 채널의 band 중심(y좌표)을 plot_widget의 화면 픽셀로 변환해,
        checkbox_area 안의 같은 y좌표에 체크박스를 둔다. plot_widget과
        checkbox_area는 같은 QHBoxLayout 행에서 위쪽이 정렬되어 있어 y값을
        그대로 재사용할 수 있다. 확대/축소/창 크기 변경에도 맞게 매
        render()마다 다시 계산한다."""
        vb = self.plot_widget.getViewBox()
        size = self._checkbox_size
        x_compute = 8
        x_draw = 8 + size + 8
        x_label = 8 + size + 8 + size + 8
        for i in range(config.N_CH):
            base_offset = (config.N_CH - 1 - i) * config.CH_OFFSET + (config.CH_OFFSET / 2)
            scene_pt = vb.mapViewToScene(QPointF(0, base_offset))
            widget_pt = self.plot_widget.mapFromScene(scene_pt)
            y = int(widget_pt.y() - size / 2)
            self.compute_checks[i].move(x_compute, y)
            self.draw_checks[i].move(x_draw, y)
            self.ch_labels[i].move(x_label, y - 2)

    def on_sample(self, raw_vals, amp_vals):
        if self.start_time_ref is None:
            return
        self.sample_count += 1

        # 링버퍼 쓰기는 "연산" 체크와 무관하게 항상 전 채널 수행 (데이터 자체는 안 끊음)
        for i in range(config.N_CH):
            self.raw_np_buf[i, self.ptr] = raw_vals[i]

        # "연산" 체크 = 오토스케일(ChannelScaler.update) 적용 여부만 결정.
        # 꺼지면 그 채널은 min/max/baseline 갱신이 멈춰서 공유 data_range
        # 계산에도 더는 새 값으로 반영되지 않는다 (데이터 자체는 계속 들어옴).
        if self.sample_count % 4 == 0:
            for i in range(config.N_CH):
                if self.active[i]:
                    self.scale_manager.scalers[i].update(raw_vals[i])

        self.ptr += 1
        if self.ptr >= self.max_display:
            self.ptr = 0
            self.is_buf_full = True

        # dashboard_ui.py와 동일한 1회성 리사이즈 로직 (자동, START 후 5초 시점 딱 한 번)
        elapsed = time.time() - self.start_time_ref
        if not self._has_resized_once and elapsed >= config.FIRST_RESIZE_AFTER_SEC and elapsed > 0:
            self._has_resized_once = True
            self._resize_to_current_rate()

    def _resize_to_current_rate(self):
        """지금까지의 누적 평균 수신 속도(sample_count/elapsed)로 새 버퍼
        길이를 계산해서 리사이즈한다. on_sample()의 1회성 자동 리사이즈와
        "버퍼 리사이즈" 버튼(수동, 몇 번이든 다시 누를 수 있음)이 공통으로
        쓰는 로직."""
        if self.start_time_ref is None or self.sample_count == 0:
            return
        elapsed = time.time() - self.start_time_ref
        if elapsed <= 0:
            return
        rate = self.sample_count / elapsed
        new_len = int(round(rate * config.PLOT_SEC))
        new_len = max(config.MIN_BUF, min(config.MAX_BUF, new_len))
        if new_len != self.max_display:
            old_len = self.max_display
            self._resize_raw_buffers(new_len)
            print(f"[resize] {old_len} -> {new_len} samples (측정 rate={rate:.0f}Hz)")
        else:
            print(f"[resize] 변화 없음 (현재 {self.max_display}, 측정 rate={rate:.0f}Hz)")

    def _on_resize_button_clicked(self):
        self._resize_to_current_rate()

    def _active_data_range_and_half_height(self):
        """emg_scale.py의 EMGScaleManager._data_range_and_half_height()와
        동일하지만, AutoScale이 꺼진(self.active[i] == False) 채널은 has_data
        여부와 무관하게 공유 data_range 계산에서 완전히 제외한다. 원본은
        한 번 has_data=True가 되면 체크를 꺼도 계속 반영되는 문제가 있었음."""
        scalers = self.scale_manager.scalers
        valid_mins = [
            scalers[i].current_min for i in range(config.N_CH)
            if self.active[i] and scalers[i].has_data and scalers[i].current_min > 0
        ]
        valid_maxs = [
            scalers[i].current_max for i in range(config.N_CH)
            if self.active[i] and scalers[i].has_data and scalers[i].current_max > 0
        ]
        if not valid_mins or not valid_maxs:
            global_min = config.RAW_Y_MIN_INIT
            global_max = config.RAW_Y_MAX_INIT
        else:
            global_min = min(valid_mins)
            global_max = max(valid_maxs)

        data_range = max(global_max - global_min, 20)
        safe_margin_factor = 0.85
        allowed_half_height = (config.CH_OFFSET / 2) * safe_margin_factor
        return data_range, allowed_half_height

    def _get_scaled_array_active(self, ch_idx: int, raw_array: np.ndarray) -> np.ndarray:
        """emg_scale.py의 EMGScaleManager.get_scaled_array()와 동일하지만,
        내부에서 (원본이 쓰는 전체-채널 기준이 아니라) 위의 AutoScale-필터링된
        data_range를 사용한다."""
        scaler = self.scale_manager.scalers[ch_idx]
        data_range, allowed_half_height = self._active_data_range_and_half_height()

        base_offset = (config.N_CH - 1 - ch_idx) * config.CH_OFFSET + (config.CH_OFFSET / 2)

        effective_raw = np.where(
            raw_array <= config.RAW_ZERO_THRESHOLD,
            config.RAW_ZERO_REF,
            raw_array,
        )
        ratios = (effective_raw - scaler.baseline) / (data_range / 2)
        ratios = np.clip(ratios, -1.0, 1.0)
        return base_offset + (ratios * allowed_half_height)

    def _resize_raw_buffers(self, new_len: int):
        """dashboard_ui.py의 _resize_raw_buffers()와 동일한 로직."""
        n_ch = config.N_CH
        old_len = self.max_display
        if self.is_buf_full:
            seq = [(self.ptr + i) % old_len for i in range(old_len)]
        else:
            seq = list(range(self.ptr))
        take = min(new_len, len(seq))
        new_raw = np.zeros((n_ch, new_len))
        new_height = np.ones((n_ch, new_len)) * 1.5
        if take > 0:
            indices = seq[-take:]
            for ch in range(n_ch):
                new_raw[ch, :take] = self.raw_np_buf[ch, indices]
                new_height[ch, :take] = self.height_buf[ch, indices]
        self.raw_np_buf = new_raw
        self.height_buf = new_height
        self.max_display = new_len
        self.x_axis = np.linspace(0, config.PLOT_SEC * 1000, new_len)
        if take >= new_len:
            self.ptr = 0
            self.is_buf_full = True
        else:
            self.ptr = take
            self.is_buf_full = False

    def render(self):
        self._reposition_channel_checkboxes()
        if self.sample_count == 0:
            return
        is_fill_mode = self.rb_fill.isChecked()
        unified_x_ms = self.x_axis[self.ptr % self.max_display]

        # graph_render.update_raw_graph()와 동일한 로직의 로컬 복사본.
        # 차이는 딱 하나: 그리기가 꺼진 채널은 맨 앞에서 continue로 건너뛰어
        # chunk 통계 계산 자체를 아예 수행하지 않는다 (원본/이전 버전은
        # 계산을 다 하고 나서 숨기기만 했음).
        for i in range(config.N_CH):
            if not self.draw_active[i]:
                self.past_lines[i].setVisible(False)
                self.raw_lines[i].setVisible(False)
                self.bar_items[i].setVisible(False)
                self.cursor_rects[i].setData(pos=[])
                continue

            data_range, allowed_half_height = self._active_data_range_and_half_height()
            max_bar_pixels = 2.0 * allowed_half_height
            half_range = max(data_range / 2.0, 1.0)

            for chunk_start in range(0, self.max_display, CHUNK_SIZE):
                chunk = self.raw_np_buf[i, chunk_start : chunk_start + CHUNK_SIZE]
                if chunk.size > 0:
                    ch_max = np.nanmax(chunk)
                    ch_min = np.nanmin(chunk)
                    if (ch_max - ch_min) < config.NO_SIGNAL_VARIATION_RAW:
                        new_h = LINE_HEIGHT_PX
                    else:
                        bar_height_raw = ch_max - ch_min
                        ratio = min(bar_height_raw / half_range, 1.0)
                        new_h = max(ratio * max_bar_pixels, LINE_HEIGHT_PX)
                    self.height_buf[i, chunk_start : chunk_start + CHUNK_SIZE] = new_h

            base_offset = (config.N_CH - 1 - i) * config.CH_OFFSET + (config.CH_OFFSET / 2)

            if is_fill_mode:
                self.past_lines[i].setVisible(False)
                self.raw_lines[i].setVisible(False)

                x_max_ms = config.PLOT_SEC * 1000
                num_bars = int(x_max_ms / config.BAR_INTERVAL_MS)
                bar_x = np.arange(num_bars, dtype=float) * config.BAR_INTERVAL_MS
                display_heights = np.zeros(num_bars)

                for b in range(num_bars):
                    center_idx = int(b * self.max_display / num_bars)
                    idx = (center_idx - CHUNK_SIZE // 2 + np.arange(CHUNK_SIZE)) % self.max_display
                    if idx.size < CHUNK_SIZE:
                        continue
                    chunk = self.raw_np_buf[i, idx]
                    ch_max = np.nanmax(chunk)
                    ch_min = np.nanmin(chunk)
                    if (ch_max - ch_min) < config.NO_SIGNAL_VARIATION_RAW:
                        h = LINE_HEIGHT_PX
                    else:
                        bar_height_raw = ch_max - ch_min
                        ratio = min(bar_height_raw / half_range, 1.0)
                        h = max(ratio * max_bar_pixels, LINE_HEIGHT_PX)
                    display_heights[b] = h
                    if not self.is_buf_full:
                        t_bar = b * config.BAR_INTERVAL_MS
                        t_gap = (self.ptr / self.max_display) * x_max_ms
                        if t_bar >= t_gap:
                            display_heights[b] = 0

                if self.is_buf_full:
                    gap_bar = int(self.ptr * num_bars / self.max_display)
                    for k in range(gap_range):
                        display_heights[(gap_bar + k) % num_bars] = 0

                self.bar_items[i].setOpts(
                    x=bar_x, height=display_heights,
                    y0=base_offset - (display_heights / 2),
                    width=min(20, config.BAR_INTERVAL_MS * 0.6),
                )
                self.bar_items[i].setVisible(True)

                last_x = (
                    self.x_axis[(self.ptr - 1) % self.max_display]
                    if self.sample_count > 0 else unified_x_ms
                )
                self.cursor_rects[i].setData(pos=[(last_x, base_offset)])

            else:
                self.bar_items[i].setVisible(False)
                ds = config.RAW_LINE_DOWNSAMPLE

                if not self.is_buf_full:
                    self.past_lines[i].setData([], [])
                    self.past_lines[i].setVisible(False)
                    if self.ptr <= 0:
                        x, y = np.array([]), np.array([])
                    else:
                        x = self.x_axis[: self.ptr : ds]
                        y = self._get_scaled_array_active(i, self.raw_np_buf[i, : self.ptr : ds])
                else:
                    x_past = self.x_axis[self.ptr :: ds]
                    y_past = self._get_scaled_array_active(i, self.raw_np_buf[i, self.ptr :: ds])
                    self.past_lines[i].setData(x_past, y_past)
                    self.past_lines[i].setVisible(True)

                    if self.ptr <= 0:
                        x, y = np.array([]), np.array([])
                    else:
                        x = self.x_axis[: self.ptr : ds]
                        y = self._get_scaled_array_active(i, self.raw_np_buf[i, : self.ptr : ds])

                self.raw_lines[i].setData(x, y)
                self.raw_lines[i].setVisible(True)

                if self.sample_count > 0:
                    prev_idx = (self.ptr - 1) % self.max_display
                    last_x = self.x_axis[prev_idx]
                    y_cursor = self._get_scaled_array_active(
                        i, np.array([self.raw_np_buf[i, prev_idx]])
                    )[0]
                    self.cursor_rects[i].setData(pos=[(last_x, y_cursor)])
                else:
                    self.cursor_rects[i].setData(pos=[])

    def closeEvent(self, event):
        self.worker.stop()
        self.worker.wait(500)
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    win = MultiChannelView()
    win.show()
    win.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
