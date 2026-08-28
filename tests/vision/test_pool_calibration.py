import importlib.util
import os
import sys
import unittest


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

CV2_AVAILABLE = importlib.util.find_spec("cv2") is not None
if CV2_AVAILABLE:
    import cv2
    import numpy as np

    from perception import build_calibration_homography
    from config import PHYSICAL_HEIGHT, PHYSICAL_WIDTH


@unittest.skipUnless(CV2_AVAILABLE, "OpenCV is required by pool calibration")
class PoolCalibrationTests(unittest.TestCase):
    def test_maps_ordered_pool_corners_to_metric_rectangle(self):
        points = [(20, 15), (620, 15), (620, 465), (20, 465)]
        homography, error = build_calibration_homography(points, 640, 480)

        self.assertIsNone(error)
        mapped = cv2.perspectiveTransform(
            np.asarray([[points[0], points[2]]], dtype=np.float32),
            homography,
        )[0]
        np.testing.assert_allclose(mapped[0], [0.0, 0.0], atol=1e-5)
        np.testing.assert_allclose(
            mapped[1], [PHYSICAL_WIDTH, PHYSICAL_HEIGHT], atol=1e-5
        )

    def test_rejects_wrong_order_and_tiny_calibration_area(self):
        _, order_error = build_calibration_homography(
            [(20, 15), (20, 465), (620, 465), (620, 15)], 640, 480
        )
        _, area_error = build_calibration_homography(
            [(10, 10), (20, 10), (20, 20), (10, 20)], 640, 480
        )

        self.assertIsNotNone(order_error)
        self.assertEqual(area_error, "标定区域过小")

