import os
import sys
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from control import VisionControlSession


def guidance(*, settled=False):
    return {
        "seg_index": 2,
        "settled": settled,
        "x_error_m": 0.1,
        "along_m": 0.2,
        "drive_distance_m": 0.8,
        "curve_severity": 0.3,
        "brake_request": False,
        "cross_track_m": 0.1,
        "heading_error_deg": 5.0,
        "path_curvature_per_m": 1.2,
        "steering_demand": 0.4,
    }


class FakePathGuidance:
    def __init__(self):
        self.prepared = True
        self.cleared = 0
        self.next_guidance = guidance()

    def start(self, path, position, timestamp, heading):
        del path, position, timestamp, heading
        return guidance()

    def update(self, position, timestamp, allow_course_update, speed_mps):
        del position, timestamp, allow_course_update, speed_mps
        return dict(self.next_guidance)

    def clear(self):
        self.cleared += 1
        self.prepared = False


class VisionControlSessionTests(unittest.TestCase):
    def setUp(self):
        self.path = FakePathGuidance()
        self.control = VisionControlSession(self.path)
        self.control.activate(guidance())

    def test_target_loss_emits_an_explicit_stop_decision(self):
        decision = self.control.update(
            calibrated=True,
            position=None,
            frame_time=1.0,
            now=1.0,
            allow_course_update=True,
            speed_mps=0.0,
        )

        self.assertTrue(decision.stop_required)
        self.assertEqual(decision.status, "TARGET LOST")
        self.assertFalse(self.control.active)

    def test_tracking_emits_bounded_rate_pid_data(self):
        first = self.control.update(
            calibrated=True,
            position=(0.2, 0.3),
            frame_time=1.0,
            now=1.0,
            allow_course_update=True,
            speed_mps=0.1,
        )
        second = self.control.update(
            calibrated=True,
            position=(0.2, 0.3),
            frame_time=1.05,
            now=1.05,
            allow_course_update=True,
            speed_mps=0.1,
        )

        self.assertIsNotNone(first.pid)
        self.assertIsNone(second.pid)
        self.assertEqual(first.pid["cross_m"], 0.1)

    def test_arrival_requires_a_stop(self):
        self.path.next_guidance = guidance(settled=True)
        decision = self.control.update(
            calibrated=True,
            position=(0.2, 0.3),
            frame_time=1.0,
            now=1.0,
            allow_course_update=True,
            speed_mps=0.1,
        )

        self.assertTrue(decision.stop_required)
        self.assertEqual(decision.status, "ARRIVED")


if __name__ == "__main__":
    unittest.main()

