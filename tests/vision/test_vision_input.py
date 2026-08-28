import importlib.util
import os
import sys
import unittest
from collections import deque


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

CV2_AVAILABLE = importlib.util.find_spec("cv2") is not None
if CV2_AVAILABLE:
    import cv2

    from ui import VisionMouseController


class FakeToolbar:
    height = 60

    def hit_test(self, x, y, width, height):
        if y >= height - self.height and x < 100:
            return "START"
        return None

    def contains(self, x, y, height):
        return y >= height - self.height


@unittest.skipUnless(CV2_AVAILABLE, "OpenCV is required by mouse input")
class VisionMouseControllerTests(unittest.TestCase):
    def setUp(self):
        self.actions = deque()
        self.drawn_path = {
            "pixels": [], "drawing": False, "active": False, "segment": 0
        }
        self.marker = {
            "selecting": False, "dragging": False, "start": None, "end": None
        }
        self.heading = {"selecting": False}
        self.calibration = {
            "H": None,
            "is_calibrating": False,
            "manual_locked": False,
            "pts_raw": [],
            "pts_disp": [],
        }
        self.pointer = {"pressed_toolbar_action": None}
        self.controller = VisionMouseController(
            frame_width=640,
            frame_height=480,
            toolbar=FakeToolbar(),
            pending_actions=self.actions,
            pointer_state=self.pointer,
            marker_roi_state=self.marker,
            heading_state=self.heading,
            calibration_state=self.calibration,
            drawn_path_state=self.drawn_path,
        )

    def test_toolbar_click_queues_action_without_starting_path(self):
        self.controller(cv2.EVENT_LBUTTONDOWN, 20, 460, 0, None)

        self.assertEqual(list(self.actions), ["START"])
        self.assertFalse(self.drawn_path["drawing"])

    def test_canvas_drag_builds_path_and_right_click_clears_it(self):
        self.controller(cv2.EVENT_LBUTTONDOWN, 120, 100, 0, None)
        self.controller(cv2.EVENT_MOUSEMOVE, 140, 120, 0, None)
        self.controller(cv2.EVENT_LBUTTONUP, 160, 140, 0, None)

        self.assertEqual(self.drawn_path["pixels"], [(120, 100), (140, 120)])
        self.controller(cv2.EVENT_RBUTTONDOWN, 160, 140, 0, None)
        self.assertEqual(self.drawn_path["pixels"], [])
        self.assertEqual(list(self.actions), ["CLEAR_PATH"])

    def test_pool_calibration_click_is_an_action_not_algorithm_coupling(self):
        self.calibration["is_calibrating"] = True
        self.controller(cv2.EVENT_LBUTTONDOWN, 25, 35, 0, None)

        self.assertEqual(list(self.actions), [("APPLY_POOL_POINT", (25, 35))])
        self.assertEqual(self.calibration["pts_raw"], [])

    def test_editing_an_active_path_requests_a_stop(self):
        self.drawn_path["active"] = True
        self.controller(cv2.EVENT_LBUTTONDOWN, 120, 100, 0, None)

        self.assertEqual(list(self.actions), ["PATH_EDIT_STARTED"])

