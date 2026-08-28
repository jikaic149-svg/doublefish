import os
import sys
import unittest
from collections import deque
from types import SimpleNamespace

import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from perception import ReferenceObservation, ReferenceSource
from ui import VisionPresentation


class FakeToolbar:
    def __init__(self):
        self.active = None

    def draw(self, image, active):
        del image
        self.active = active


class FakeHud:
    SOURCE_NAMES = {ReferenceSource.MARKER: "鱼尾色标"}

    def draw(self, image, **kwargs):
        del image, kwargs


class VisionPresentationTests(unittest.TestCase):
    def test_render_accepts_snapshots_without_touching_services(self):
        toolbar = FakeToolbar()
        presentation = VisionPresentation(toolbar, FakeHud(), deque(maxlen=10))
        reference = ReferenceObservation(
            timestamp=1.0,
            source=ReferenceSource.MARKER,
            position=(20.0, 30.0),
            confidence=0.9,
            quality=0.9,
            marker_profiled=True,
            yolo_confirmed=True,
            usable_for_pwm_speed=True,
            metrics={"tail_marker_position": (20.0, 30.0)},
        )
        result = SimpleNamespace(
            frame=np.zeros((100, 120, 3), dtype=np.uint8),
            frame_time=1.0,
            corner_pixels={},
            reference=reference,
            display_pixel=(20, 30),
            pixel=(20.0, 30.0),
            current_position=(0.2, 0.3),
            control_position=(0.2, 0.3),
            speed=0.1,
            direction_deg=0.0,
            yolo_bbox=None,
            yolo_status={"loading": False, "error": None},
            yolo_fps=5.0,
        )
        calibration = {"H": None, "is_calibrating": False, "pts_raw": []}
        marker = {
            "selecting": False, "start": None, "end": None,
            "confirmed_bbox": None, "confirmed_center": None,
            "confirmed_until": 0.0,
        }
        heading = {
            "selecting": False, "tail_point": None, "head_point": None,
            "confirmed_until": 0.0,
        }
        path = {"pixels": []}
        turn = SimpleNamespace(active=False, sample_count=0)

        image = presentation.render(
            result,
            calibration=calibration,
            marker_roi=marker,
            heading=heading,
            drawn_path=path,
            decision=None,
            control_active=False,
            turn_session=turn,
            status="READY",
            recording=False,
            camera_fps=60.0,
            loop_fps=60.0,
            exposure=-6,
            tablet_rates=(0.0, 0.0),
            mcu_hz=0.0,
            clahe_enabled=True,
        )

        self.assertEqual(image.shape, (100, 120, 3))
        self.assertTrue(toolbar.active["CLAHE"])


if __name__ == "__main__":
    unittest.main()

