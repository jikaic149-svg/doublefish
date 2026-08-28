import os
import sys
import unittest

import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from ui import (  # noqa: E402
    VisionHud,
    VisionToolbar,
    fit_preview_window_size,
    map_screen_point_to_frame,
)


class VisionToolbarTests(unittest.TestCase):
    def test_every_button_can_be_hit(self):
        toolbar = VisionToolbar()
        rectangles = toolbar.layout(640, 480)
        self.assertEqual(len(rectangles), 13)
        self.assertIn("TURN_CALIB", rectangles)
        for action, (x1, y1, x2, y2) in rectangles.items():
            hit = toolbar.hit_test((x1 + x2) // 2, (y1 + y2) // 2, 640, 480)
            self.assertEqual(hit, action)

    def test_canvas_is_not_toolbar(self):
        toolbar = VisionToolbar()
        self.assertFalse(toolbar.contains(100, 100, 480))
        self.assertTrue(toolbar.contains(100, 470, 480))

    def test_toolbar_draws_only_in_bottom_panel(self):
        toolbar = VisionToolbar()
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        toolbar.draw(image, active={"STOP": True, "MARKER_ROI": True})
        self.assertEqual(int(np.count_nonzero(image[:400])), 0)
        self.assertGreater(int(np.count_nonzero(image[404:])), 1000)

    def test_preview_window_uses_most_of_a_1080p_screen(self):
        self.assertEqual(
            fit_preview_window_size(640, 480, 1920, 1080),
            (1296, 972),
        )

    def test_absolute_windows_pointer_maps_into_camera_frame(self):
        image_rectangle = (100, 50, 1296, 972)
        self.assertEqual(
            map_screen_point_to_frame(748, 536, image_rectangle, 640, 480),
            (320, 240),
        )
        self.assertIsNone(
            map_screen_point_to_frame(99, 536, image_rectangle, 640, 480)
        )

    def test_chinese_hud_is_compact_and_keeps_centre_clear(self):
        hud = VisionHud()
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        hud.draw(
            image,
            source="INVALID",
            status="READY",
            quality=0.0,
            pwm_ready=False,
            position=None,
            speed=None,
            direction_deg=None,
            gate_reasons=["MARKER_NOT_CALIBRATED"],
            loop_fps=30.0,
            camera_fps=30.0,
            yolo_fps=29.5,
            exposure=-5,
            tablet_tx_hz=0.0,
            tablet_rx_hz=0.0,
            mcu_hz=0.0,
        )
        self.assertGreater(int(np.count_nonzero(image[:140])), 1000)
        self.assertEqual(int(np.count_nonzero(image[200:390, 100:540])), 0)


if __name__ == "__main__":
    unittest.main()

