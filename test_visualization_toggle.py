import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
CLIENT_APP = Path(__file__).resolve().parent / "client_app"
sys.path.insert(0, str(CLIENT_APP))

from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QCheckBox

from dashboard_ui import EMGDashboard, VisualizationSwitch
from graph_render import update_fft_graph
import config


class VisualizationToggleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.dashboard = EMGDashboard()

    def tearDown(self):
        self.dashboard.timer.stop()
        self.dashboard.close()

    def test_switch_matches_dashboard_palette_and_has_a_large_hit_area(self):
        switch = VisualizationSwitch()

        self.assertEqual(switch.width(), 54)
        self.assertEqual(switch.height(), 34)
        self.assertEqual(switch.ACTIVE_TRACK, "#738cff")
        self.assertEqual(switch.INACTIVE_TRACK, "#1c2538")
        self.assertEqual(switch.BORDER, "#3d4d75")
        self.assertFalse(switch.STATE_TEXT_VISIBLE)

    def test_the_entire_switch_surface_is_clickable(self):
        switch = VisualizationSwitch()

        self.assertTrue(switch.hitButton(QPoint(2, switch.height() // 2)))
        self.assertTrue(
            switch.hitButton(QPoint(switch.width() - 2, switch.height() // 2))
        )

    def test_bar_mode_shows_and_updates_the_receive_rate(self):
        self.dashboard._apply_raw_fill()
        self.assertFalse(self.dashboard.sample_rate_label.isHidden())

        self.dashboard._update_sample_rate_label = Mock()
        self.dashboard.is_running = True
        self.dashboard.start_time_ref = time.time()
        self.dashboard.on_sample(
            [100] * len(self.dashboard.last_amp),
            np.zeros_like(self.dashboard.last_amp),
        )

        self.dashboard._update_sample_rate_label.assert_called_once_with()

    def test_fft_render_avoids_repeated_layout_updates(self):
        sample_count = min(1024, self.dashboard.max_display)
        self.dashboard.is_running = True
        self.dashboard.sample_count = sample_count
        self.dashboard.ptr = sample_count
        self.dashboard.start_time_ref = 1000.0
        self.dashboard.raw_np_buf[:, :sample_count] = np.tile(
            np.arange(sample_count) % 2 * 200,
            (config.N_CH, 1),
        )
        self.dashboard.fft_plot.setTitle = Mock()
        self.dashboard.graph_panel_title_label.setText = Mock()

        with patch("graph_render.time.monotonic", side_effect=(10.0, 10.8)):
            update_fft_graph(self.dashboard)
            update_fft_graph(self.dashboard)

        self.dashboard.fft_plot.setTitle.assert_not_called()
        self.dashboard.graph_panel_title_label.setText.assert_called_once()

    def test_fft_magnitude_is_not_hard_clipped(self):
        sample_count = min(1024, self.dashboard.max_display)
        self.dashboard.is_running = True
        self.dashboard.sample_count = sample_count
        self.dashboard.ptr = sample_count
        self.dashboard.start_time_ref = 1000.0
        self.dashboard.raw_np_buf[:, :sample_count] = np.tile(
            np.arange(sample_count) % 2 * 10000,
            (config.N_CH, 1),
        )

        with patch("graph_render.time.monotonic", return_value=10.0):
            update_fft_graph(self.dashboard)

        _, y_values = self.dashboard.fft_lines[0].getData()
        channel_top = config.N_CH * config.CH_OFFSET
        self.assertGreater(float(np.max(y_values)), channel_top)

    def test_fft_restores_the_original_top_spacing(self):
        sample_count = min(1024, self.dashboard.max_display)
        self.dashboard.is_running = True
        self.dashboard.sample_count = sample_count
        self.dashboard.ptr = sample_count
        self.dashboard.start_time_ref = 1000.0
        self.dashboard.raw_np_buf[:, :sample_count] = 100

        with patch("graph_render.time.time", return_value=1001.0):
            update_fft_graph(self.dashboard)

        expected_top = config.N_CH * config.CH_OFFSET + 1.5 * config.CH_OFFSET
        actual_top = self.dashboard.fft_plot.getViewBox().viewRange()[1][1]
        self.assertAlmostEqual(actual_top, expected_top)

    def test_fft_uses_the_original_session_average_sample_rate(self):
        sample_count = min(200, self.dashboard.max_display)
        self.dashboard.is_running = True
        self.dashboard.sample_count = sample_count
        self.dashboard.ptr = sample_count
        # START는 990초, 첫 샘플은 BLE 연결 후 1000초에 도착 → fs는 첫 샘플 기준으로 계산돼야 함
        self.dashboard.start_time_ref = 990.0
        self.dashboard.first_sample_time = 1000.0
        self.dashboard.sample_rate = Mock(hz=800.0)
        self.dashboard.raw_np_buf[:, :sample_count] = 100

        with (
            patch("graph_render.time.time", return_value=1001.0),
            patch("graph_render.time.monotonic", side_effect=(10.0, 10.8)),
        ):
            update_fft_graph(self.dashboard)
            update_fft_graph(self.dashboard)

        self.assertEqual(self.dashboard._fft_last_max_freq, 100.0)
        self.assertIn("fs≈200Hz", self.dashboard.graph_panel_title_label.text())
        actual_x_top = self.dashboard.fft_plot.getViewBox().viewRange()[0][1]
        self.assertEqual(actual_x_top, 100.0)
        fft_x, _ = self.dashboard.fft_lines[0].getData()
        self.assertLessEqual(float(np.max(fft_x)), 100.0)

    def test_fft_uses_the_original_power_of_two_startup_window(self):
        sample_count = min(200, self.dashboard.max_display)
        self.dashboard.is_running = True
        self.dashboard.sample_count = sample_count
        self.dashboard.ptr = sample_count
        self.dashboard.start_time_ref = 1000.0
        self.dashboard.raw_np_buf[:, :sample_count] = 100

        with (
            patch("graph_render.time.time", return_value=1001.0),
            patch("graph_render.time.monotonic", return_value=10.0),
        ):
            update_fft_graph(self.dashboard)

        fft_x, _ = self.dashboard.fft_lines[0].getData()
        self.assertEqual(len(fft_x), 65)

    def test_fft_does_not_blank_when_the_ring_buffer_wraps(self):
        sample_count = self.dashboard.max_display
        self.dashboard.is_running = True
        self.dashboard.sample_count = sample_count
        self.dashboard.ptr = 0
        self.dashboard.is_buf_full = True
        self.dashboard.start_time_ref = 1000.0
        self.dashboard.raw_np_buf[:, :] = 100

        with (
            patch("graph_render.time.time", return_value=1001.0),
            patch("graph_render.time.monotonic", return_value=10.0),
        ):
            update_fft_graph(self.dashboard)

        fft_x, _ = self.dashboard.fft_lines[0].getData()
        self.assertGreater(len(fft_x), 0)

    def test_each_toggle_keeps_the_graph_frame_visible(self):
        cases = (
            ("line", "btn_toggle_line", "stacked_plots"),
            ("diagonal", "btn_toggle_diagonal", "diag_plot"),
            ("power", "btn_toggle_power", "pwr_plot"),
        )

        for key, button_name, plot_name in cases:
            button = getattr(self.dashboard, button_name)
            plot = getattr(self.dashboard, plot_name)

            if key == "line":
                self.dashboard.raw_lines[0].setData([0, 1], [1, 2])
                self.dashboard.fft_lines[0].setData([0, 1], [2, 3])
            elif key == "diagonal":
                self.dashboard.diag_lines[0].setData([0, 1], [3, 4])
            else:
                self.dashboard.bar_item.setOpts(
                    height=[50] * (len(self.dashboard.last_amp) + 1)
                )

            button.click()
            self.assertFalse(self.dashboard.visualization_enabled[key])
            self.assertFalse(plot.isHidden())
            self.assertIsInstance(button, QCheckBox)
            self.assertFalse(button.isChecked())

            if key == "line":
                raw_x = self.dashboard.raw_lines[0].getData()[0]
                fft_x = self.dashboard.fft_lines[0].getData()[0]
                self.assertTrue(raw_x is None or len(raw_x) == 0)
                self.assertTrue(fft_x is None or len(fft_x) == 0)
            elif key == "diagonal":
                diag_x = self.dashboard.diag_lines[0].getData()[0]
                self.assertTrue(diag_x is None or len(diag_x) == 0)
            else:
                self.assertTrue(
                    np.all(np.asarray(self.dashboard.bar_item.opts["height"]) == 0)
                )

    def test_turning_a_visualization_back_on_resets_all_visualizations(self):
        self.dashboard.raw_np_buf.fill(123)
        self.dashboard.ptr = 17
        self.dashboard.is_buf_full = True
        self.dashboard.last_amp.fill(42)
        original_start_time = 1234.5
        self.dashboard.start_time_ref = original_start_time
        self.dashboard.sample_count = 99

        self.dashboard.btn_toggle_diagonal.click()  # OFF
        self.dashboard.btn_toggle_diagonal.click()  # ON + common reset

        self.assertTrue(self.dashboard.visualization_enabled["diagonal"])
        self.assertFalse(self.dashboard.diag_plot.isHidden())
        self.assertTrue(np.all(self.dashboard.raw_np_buf == 0))
        self.assertTrue(np.all(self.dashboard.last_amp == 0))
        self.assertEqual(self.dashboard.ptr, 0)
        self.assertFalse(self.dashboard.is_buf_full)
        self.assertEqual(self.dashboard.sample_count, 99)
        self.assertEqual(self.dashboard.start_time_ref, original_start_time)
        self.assertIsInstance(self.dashboard.btn_toggle_diagonal, QCheckBox)
        self.assertTrue(self.dashboard.btn_toggle_diagonal.isChecked())

    def test_turning_line_off_after_fill_mode_clears_bars_and_cursors(self):
        self.dashboard.is_running = True
        self.dashboard.start_time_ref = time.time()
        for _ in range(200):
            self.dashboard.on_sample([100] * config.N_CH, np.zeros(config.N_CH))
        self.dashboard._apply_raw_fill()
        self.dashboard.render()

        self.dashboard.btn_toggle_line.click()  # OFF

        self.assertEqual(len(self.dashboard.bar_items[0].opts["x"]), 0)
        cursor_x = self.dashboard.cursor_rects[0].getData()[0]
        self.assertTrue(cursor_x is None or len(cursor_x) == 0)

    def test_spinbox_up_and_down_buttons_are_not_covered_by_the_text_field(self):
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QStyle, QStyleOptionSpinBox

        self.dashboard.show()
        for sb in (self.dashboard.sp_samples,):
            for sub, delta in (
                (QStyle.SubControl.SC_SpinBoxUp, sb.singleStep()),
                (QStyle.SubControl.SC_SpinBoxDown, -sb.singleStep()),
            ):
                opt = QStyleOptionSpinBox()
                sb.initStyleOption(opt)
                rect = sb.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, opt, sub, sb)
                # 실제 마우스처럼, 그 자리에 있는 맨 위 위젯(텍스트 칸일 수도 있음)이 클릭을 받게 한다
                target = sb.childAt(rect.center()) or sb
                before = sb.value()
                QTest.qWait(700)  # 연속 클릭이 더블클릭(Windows 기본 500ms)으로 잡히지 않게
                QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFrom(sb, rect.center()))
                self.assertEqual(sb.value(), before + delta)

    def _render_fill(self):
        from graph_render import update_raw_graph
        d = self.dashboard
        update_raw_graph(d, True, d.x_axis[d.ptr % d.max_display], d.ptr)
        return d.bar_items[0].opts

    def test_fill_mode_splits_visual_samples_into_one_hundredth_segments(self):
        d = self.dashboard
        d.sample_count = 1
        for n in (1500, 3000):
            d.sp_samples.setValue(n)
            d.raw_np_buf.fill(100)
            d.is_buf_full = True
            d.ptr = n // 2
            opts = self._render_fill()
            self.assertEqual(len(opts["x"]), config.RAW_FILL_BARS)
            spacing = opts["x"][1] - opts["x"][0]
            self.assertAlmostEqual(spacing, n / config.RAW_FILL_BARS)

    def test_first_fill_bar_does_not_mix_in_samples_from_the_end_of_the_buffer(self):
        d = self.dashboard
        d.sample_count = 1
        d.sp_samples.setValue(2000)
        seg = 2000 // config.RAW_FILL_BARS
        d.raw_np_buf.fill(100)
        d.raw_np_buf[:, -seg:] = np.tile([60, 160], seg // 2)   # 마지막 구간만 크게 흔들림
        d.is_buf_full = True
        d.ptr = 1000
        heights = np.asarray(self._render_fill()["height"])
        self.assertAlmostEqual(heights[0], 1.5)        # 첫 구간은 평평 → 최소 높이
        self.assertGreater(heights[-1], heights[0])    # 마지막 구간만 높음

    def test_x_samples_setting_starts_from_config_value(self):
        self.assertEqual(self.dashboard.sp_samples.value(), config.RAW_DISPLAY_SAMPLES)
        self.assertEqual(self.dashboard.max_display, config.RAW_DISPLAY_SAMPLES)

    def test_changing_x_samples_resizes_buffer_and_axis_while_running(self):
        self.dashboard.is_running = True
        self.dashboard.start_time_ref = time.time()
        self.dashboard.sample_count = 500
        self.dashboard.raw_np_buf.fill(123)
        self.dashboard.ptr = 40
        self.dashboard.is_buf_full = True

        self.dashboard.sp_samples.setValue(3000)

        self.assertEqual(self.dashboard.max_display, 3000)
        self.assertEqual(self.dashboard.raw_np_buf.shape, (config.N_CH, 3000))
        self.assertTrue(np.all(self.dashboard.raw_np_buf == 0))
        self.assertEqual(len(self.dashboard.x_axis), 3000)
        self.assertEqual(self.dashboard.x_axis[-1], 2999)
        self.assertEqual(self.dashboard.ptr, 0)
        self.assertFalse(self.dashboard.is_buf_full)
        self.assertEqual(self.dashboard.sample_count, 500)
        x_range = self.dashboard.raw_plot.getViewBox().viewRange()[0]
        self.assertAlmostEqual(x_range[0], 0)
        self.assertAlmostEqual(x_range[1], 3000)

        self.dashboard.on_sample(
            [100] * config.N_CH, np.zeros(config.N_CH)
        )
        self.assertEqual(self.dashboard.ptr, 1)


if __name__ == "__main__":
    unittest.main()
