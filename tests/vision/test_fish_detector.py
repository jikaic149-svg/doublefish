import os
import sys
import threading
import time
import unittest

import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from perception import FishDetector


def wait_until(predicate, timeout=1.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class FakeModel:
    def __init__(self):
        self.frames = []
        self.kwargs = []

    def predict(self, frame, **kwargs):
        self.frames.append(int(frame[0, 0, 0]))
        self.kwargs.append(kwargs)
        return []


class FishDetectorTests(unittest.TestCase):
    def test_start_returns_while_loader_is_blocked_and_keeps_latest_frame(self):
        release_loader = threading.Event()
        model = FakeModel()

        def factory(_):
            release_loader.wait(1.0)
            return model

        detector = FishDetector("fake.pt", model_factory=factory)
        started = time.perf_counter()
        detector.start()
        self.assertLess(time.perf_counter() - started, 0.10)
        self.assertTrue(detector.get_status()["loading"])

        detector.submit_frame(np.full((1, 1, 3), 1, np.uint8), 1.0)
        detector.submit_frame(np.full((1, 1, 3), 2, np.uint8), 2.0)
        release_loader.set()
        self.assertTrue(wait_until(lambda: len(model.frames) == 1))
        self.assertEqual(model.frames, [2])
        self.assertTrue(detector.get_status()["ready"])
        self.assertEqual(model.kwargs[0]["max_det"], 3)
        self.assertAlmostEqual(model.kwargs[0]["iou"], 0.50)
        self.assertTrue(detector.close())

    def test_load_error_is_reported(self):
        def factory(_):
            raise RuntimeError("bad model")

        detector = FishDetector("bad.pt", model_factory=factory).start()
        self.assertTrue(wait_until(lambda: not detector.get_status()["loading"]))
        status = detector.get_status()
        self.assertFalse(status["ready"])
        self.assertIn("bad model", status["error"])
        self.assertTrue(detector.close())

    def test_close_clears_loading_and_ready_status(self):
        release_loader = threading.Event()

        def factory(_):
            release_loader.wait(1.0)
            return FakeModel()

        detector = FishDetector("fake.pt", model_factory=factory).start()
        self.assertTrue(detector.get_status()["loading"])
        self.assertFalse(detector.close(timeout=0.01))
        status = detector.get_status()
        self.assertFalse(status["loading"])
        self.assertFalse(status["ready"])
        release_loader.set()
        self.assertTrue(wait_until(lambda: not detector.thread.is_alive()))

    def test_inference_error_does_not_kill_worker(self):
        class FlakyModel(FakeModel):
            def predict(self, frame, **kwargs):
                value = int(frame[0, 0, 0])
                if value == 1:
                    raise RuntimeError("bad frame")
                return super().predict(frame, **kwargs)

        model = FlakyModel()
        detector = FishDetector(
            "fake.pt", model_factory=lambda _: model
        ).start()
        self.assertTrue(wait_until(lambda: detector.get_status()["ready"]))
        detector.submit_frame(np.full((1, 1, 3), 1, np.uint8), 1.0)
        self.assertTrue(wait_until(
            lambda: detector.get_status()["last_inference_error"] is not None
        ))
        detector.submit_frame(np.full((1, 1, 3), 2, np.uint8), 2.0)
        self.assertTrue(wait_until(lambda: model.frames == [2]))
        self.assertIsNone(detector.get_status()["last_inference_error"])
        self.assertTrue(detector.close())


if __name__ == "__main__":
    unittest.main()

