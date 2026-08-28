import os
import sys
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RUNTIME_DIR = os.path.join(PROJECT_DIR, "VISION", "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from tracking import FishTrackManager, deduplicate_detections


def det(class_id, x, y, timestamp, confidence=0.8, size=20):
    return {
        "class_id": class_id,
        "bbox": [x - size / 2, y - size / 2, x + size / 2, y + size / 2],
        "confidence": confidence,
        "timestamp": timestamp,
    }


class FishTrackingTests(unittest.TestCase):
    def test_red_and_blue_tracks_are_independent(self):
        manager = FishTrackManager()
        tracks = manager.step(0.0, [det(0, 10, 10, 0.0), det(1, 100, 100, 0.0)])
        self.assertEqual(tracks["red_fish"].position, (10.0, 10.0))
        self.assertEqual(tracks["blue_fish"].position, (100.0, 100.0))

    def test_duplicate_boxes_are_reduced_per_class(self):
        detections = [det(0, 10, 10, 0.0, 0.8), det(0, 11, 10, 0.0, 0.7), det(1, 80, 80, 0.0)]
        selected = deduplicate_detections(detections)
        self.assertEqual([item.class_name for item in selected], ["red_fish", "blue_fish"])

    def test_large_jump_is_rejected_but_track_coasts(self):
        manager = FishTrackManager()
        manager.step(0.0, [det(0, 10, 10, 0.0)])
        manager.step(0.1, [det(0, 20, 10, 0.1)])
        result = manager.step(0.2, [det(0, 1000, 1000, 0.2)])["red_fish"]
        self.assertTrue(result.valid)
        self.assertEqual(result.source, "PREDICTED")
        self.assertIn("MAHALANOBIS_GATE", result.gate_reasons)

    def test_prediction_times_out(self):
        manager = FishTrackManager()
        manager.step(0.0, [det(0, 10, 10, 0.0)])
        result = manager.step(0.5, [])["red_fish"]
        self.assertFalse(result.valid)
        self.assertEqual(result.source, "INVALID")

    def test_output_deadband_holds_small_jitter(self):
        manager = FishTrackManager()
        first = manager.step(0.0, [det(0, 100, 100, 0.0)])["red_fish"]
        second = manager.step(0.1, [det(0, 101, 100, 0.1)])["red_fish"]
        self.assertEqual(second.position, first.position)


if __name__ == "__main__":
    unittest.main()
