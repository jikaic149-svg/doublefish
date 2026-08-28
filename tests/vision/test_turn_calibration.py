import io
import math
import os
import sys
import unittest
from unittest import mock

import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from navigation import (  # noqa: E402
    TurnCalibrationError,
    TurnCalibrationSession,
    fit_turn_circle,
    load_turn_calibrations,
    save_turn_calibration,
)


def circular_samples(
    direction="LEFT",
    radius=0.20,
    coverage_deg=330.0,
    count=140,
    noise_m=0.002,
    seed=7,
):
    sign = -1.0 if direction == "LEFT" else 1.0
    angles = 0.7 + sign * np.linspace(
        0.0, math.radians(coverage_deg), count
    )
    rng = np.random.default_rng(seed)
    radial_noise = rng.normal(0.0, noise_m, count)
    radii = radius + radial_noise
    points = np.column_stack((
        1.2 + radii * np.cos(angles),
        0.7 + radii * np.sin(angles),
    ))
    timestamps = np.linspace(10.0, 15.0, count)
    return points, timestamps


class TurnCalibrationTests(unittest.TestCase):
    def test_fits_left_circle_in_world_coordinates_with_y_down(self):
        points, timestamps = circular_samples("LEFT", radius=0.21)
        result = fit_turn_circle(points, timestamps)
        self.assertEqual(result.direction, "LEFT")
        self.assertAlmostEqual(result.radius_m, 0.21, delta=0.006)
        self.assertGreater(result.arc_coverage_deg, 300.0)
        self.assertLess(result.rms_residual_m, 0.006)

    def test_fits_right_circle(self):
        points, timestamps = circular_samples("RIGHT", radius=0.18)
        result = fit_turn_circle(points, timestamps)
        self.assertEqual(result.direction, "RIGHT")
        self.assertAlmostEqual(result.radius_m, 0.18, delta=0.006)

    def test_tail_wag_and_small_outlier_set_are_rejected_robustly(self):
        points, timestamps = circular_samples(
            "LEFT", radius=0.20, coverage_deg=420.0, count=180,
            noise_m=0.003,
        )
        angles = np.linspace(0.0, 12.0 * math.pi, len(points))
        center = np.asarray((1.2, 0.7))
        radial = points - center
        radial /= np.linalg.norm(radial, axis=1)[:, None]
        points += radial * (0.010 * np.sin(angles))[:, None]
        points[[20, 70, 130]] += np.asarray((0.30, -0.25))

        result = fit_turn_circle(points, timestamps)
        self.assertEqual(result.direction, "LEFT")
        self.assertAlmostEqual(result.radius_m, 0.20, delta=0.015)
        self.assertLess(result.inlier_count, result.sample_count)

    def test_rejects_arc_shorter_than_half_circle(self):
        points, timestamps = circular_samples(
            "RIGHT", coverage_deg=120.0, count=80
        )
        with self.assertRaisesRegex(TurnCalibrationError, "圆弧覆盖不足"):
            fit_turn_circle(points, timestamps)

    def test_session_ignores_duplicate_frames(self):
        session = TurnCalibrationSession(min_sample_spacing_m=0.003)
        session.start((0.0, 0.0), 1.0)
        self.assertFalse(session.add((0.0, 0.0), 1.0))
        self.assertFalse(session.add((0.001, 0.0), 1.1))
        self.assertTrue(session.add((0.010, 0.0), 1.2))
        self.assertEqual(session.sample_count, 2)

    def test_saves_left_and_right_results_in_one_local_file(self):
        left_points, left_times = circular_samples("LEFT", seed=1)
        right_points, right_times = circular_samples("RIGHT", seed=2)
        left = fit_turn_circle(left_points, left_times)
        right = fit_turn_circle(right_points, right_times)

        files = {}

        class MemoryWriter(io.StringIO):
            def __init__(self, path):
                super().__init__()
                self.path = path

            def close(self):
                if not self.closed:
                    files[self.path] = self.getvalue()
                super().close()

        def memory_open(path, mode="r", encoding=None):
            path = os.fspath(path)
            if "w" in mode:
                return MemoryWriter(path)
            return io.StringIO(files[path])

        def memory_replace(source, destination):
            files[os.fspath(destination)] = files.pop(os.fspath(source))

        path = os.path.join(VISION_DIR, "configs", "turn_calibration.local.json")
        with (
            mock.patch("builtins.open", side_effect=memory_open),
            mock.patch(
                "navigation.os.path.exists",
                side_effect=lambda candidate: os.fspath(candidate) in files,
            ),
            mock.patch("navigation.os.makedirs"),
            mock.patch(
                "navigation.os.replace", side_effect=memory_replace
            ),
        ):
            save_turn_calibration(path, left)
            save_turn_calibration(path, right)
            loaded = load_turn_calibrations(path)
        self.assertEqual(set(loaded), {"LEFT", "RIGHT"})
        self.assertAlmostEqual(loaded["LEFT"].radius_m, left.radius_m)
        self.assertAlmostEqual(loaded["RIGHT"].radius_m, right.radius_m)


if __name__ == "__main__":
    unittest.main()
