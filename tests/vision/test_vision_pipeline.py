import os
import sys
import unittest

import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from perception import ReferenceObservation, ReferenceSource
from perception import VisionPipeline
from navigation import VelocityEstimator, compensate_camera_latency


class FakeDetector:
    def __init__(self):
        self.submitted = []

    def submit_frame(self, frame, timestamp):
        self.submitted.append((frame.shape, timestamp))

    def get_latest(self):
        return {
            "pixel": [10.0, 20.0], "bbox": [1, 2, 30, 40],
            "confidence": 0.8, "track_id": None,
            "frame_time": 1.0, "infer_fps": 5.0,
        }

    def get_status(self):
        return {
            "loading": False, "ready": True, "error": None,
            "last_inference_error": None, "load_seconds": 0.1,
        }


class FakeTracker:
    def __init__(self, source=ReferenceSource.MARKER):
        self.source = source

    def update(self, **kwargs):
        del kwargs
        return ReferenceObservation(
            timestamp=1.0,
            source=self.source,
            position=(10.0, 20.0),
            confidence=0.9,
            quality=0.9,
            marker_profiled=True,
            yolo_confirmed=True,
            usable_for_pwm_speed=True,
            metrics={"tail_marker_position": (10.0, 20.0)},
        )


class VisionPipelineTests(unittest.TestCase):
    def test_marker_frame_becomes_a_metric_snapshot(self):
        detector = FakeDetector()
        pipeline = VisionPipeline(
            detector, FakeTracker(), VelocityEstimator(),
            compensate_camera_latency,
        )
        frame = np.zeros((64, 64, 3), dtype=np.uint8)

        result = pipeline.process(frame, 1.0, np.eye(3, dtype=np.float32))

        self.assertEqual(result.pixel, (10.0, 20.0))
        self.assertEqual(result.current_position, (10.0, 20.0))
        self.assertEqual(result.direct_marker_world_position, (10.0, 20.0))
        self.assertEqual(len(detector.submitted), 1)

    def test_yolo_fallback_never_becomes_a_control_position(self):
        pipeline = VisionPipeline(
            FakeDetector(), FakeTracker(ReferenceSource.ESTIMATED_FALLBACK),
            VelocityEstimator(), compensate_camera_latency,
        )
        frame = np.zeros((64, 64, 3), dtype=np.uint8)

        result = pipeline.process(frame, 1.0, np.eye(3, dtype=np.float32))

        self.assertIsNone(result.current_position)
        self.assertIsNone(result.control_position)


if __name__ == "__main__":
    unittest.main()

