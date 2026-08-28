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


def sf_guidance(*, settled=False):
    value = guidance(settled=settled)
    value.update({
        "frenet": {
            "s_m": 0.2,
            "f_m": 0.06,
            "heading_error_deg": 7.0,
            "speed_mps": 0.12,
            "yaw_rate_rps": 0.18,
        },
        "command": {
            "s_m": 0.2,
            "f_m": 0.06,
            "desired_yaw_rate_rps": 0.42,
            "turn_demand": 0.4,
            "drive_distance_m": 0.8,
            "curve_severity": 0.3,
            "brake_request": False,
        },
    })
    return value


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

    def test_frenet_fields_are_the_canonical_pid_input(self):
        self.path.next_guidance = sf_guidance()
        first = self.control.update(
            calibrated=True,
            position=(0.2, 0.3),
            frame_time=1.0,
            now=1.0,
            allow_course_update=True,
            speed_mps=0.1,
        )
        self.assertAlmostEqual(first.pid["s_m"], 0.2)
        self.assertAlmostEqual(first.pid["f_m"], 0.06)
        self.assertAlmostEqual(first.pid["yaw_rate_rps"], 0.18)
        self.assertAlmostEqual(first.pid["desired_yaw_rate_rps"], 0.42)
        # Old names remain only as aliases for the HTTP adapter/replay code.
        self.assertAlmostEqual(first.pid["cross_m"], first.pid["f_m"])
        self.assertAlmostEqual(first.pid["along_m"], first.pid["s_m"])


if __name__ == "__main__":
    unittest.main()
