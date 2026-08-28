import math
import os
import sys
import unittest

import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from navigation import (
    HeadingEstimator,
    PathGuidance,
    VelocityEstimator,
    compensate_camera_latency,
    resample_polyline,
)


class PathGuidanceTests(unittest.TestCase):
    def test_camera_latency_compensation_predicts_and_limits_position(self):
        predicted = compensate_camera_latency(
            (1.0, 2.0), (0.30, -0.10), 0.30, max_prediction_m=0.12
        )
        np.testing.assert_allclose(predicted, [1.09, 1.97])

        limited = compensate_camera_latency(
            (1.0, 2.0), (1.0, 0.0), 0.30, max_prediction_m=0.12
        )
        np.testing.assert_allclose(limited, [1.12, 2.0])

    def test_resample_is_nearly_uniform_and_keeps_endpoint(self):
        sampled = resample_polyline([(0.0, 0.0), (0.10, 0.0)], 0.03)
        np.testing.assert_allclose(sampled[:, 0], [0.0, 0.03, 0.06, 0.09, 0.10])
        np.testing.assert_allclose(sampled[:, 1], 0.0)

    def test_duplicate_points_are_removed(self):
        sampled = resample_polyline(
            [(0.0, 0.0), (0.0, 0.0), (0.06, 0.0)], 0.03
        )
        np.testing.assert_allclose(sampled[:, 0], [0.0, 0.03, 0.06])

    def test_screen_coordinates_report_fish_left_as_positive(self):
        guidance = PathGuidance(lookahead_m=0.20)
        guidance.start(
            [(0.0, -0.10), (1.0, -0.10)],
            position=(0.0, 0.0),
            timestamp=0.0,
            initial_heading=(1.0, 0.0),
        )
        left = guidance.update((0.0, 0.0), 0.1, allow_course_update=False)
        self.assertGreater(left["body_left_m"], 0.0)
        self.assertGreater(left["x_error_m"], 0.0)

        guidance.start(
            [(0.0, 0.10), (1.0, 0.10)],
            position=(0.0, 0.0),
            timestamp=0.0,
            initial_heading=(1.0, 0.0),
        )
        right = guidance.update((0.0, 0.0), 0.1, allow_course_update=False)
        self.assertLess(right["body_left_m"], 0.0)
        self.assertLess(right["x_error_m"], 0.0)

    def test_target_behind_still_commands_a_stable_full_turn(self):
        guidance = PathGuidance(lookahead_m=0.15)
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)],
            position=(0.0, 0.0),
            timestamp=0.0,
            initial_heading=(-1.0, 0.0),
        )
        positive_noise = guidance.update(
            (0.0, 1e-10), 0.1, allow_course_update=False
        )
        negative_noise = guidance.update(
            (0.0, -1e-10), 0.2, allow_course_update=False
        )
        self.assertAlmostEqual(
            positive_noise["x_error_m"], positive_noise["max_x_error_m"], places=6
        )
        self.assertAlmostEqual(
            negative_noise["x_error_m"], negative_noise["max_x_error_m"], places=6
        )
        self.assertAlmostEqual(
            abs(negative_noise["heading_error_deg"]), 180.0, places=6
        )

    def test_rear_target_keeps_same_turn_across_angle_wrap(self):
        guidance = PathGuidance(lookahead_m=0.15)
        first = guidance.start(
            [(0.0, 0.0), (1.0, 0.0)],
            position=(0.0, 0.02),
            timestamp=0.0,
            initial_heading=(-1.0, 0.0),
        )
        across_wrap = guidance.update(
            (0.0, -0.02), 0.1, allow_course_update=False
        )
        self.assertLess(first["heading_error_deg"], -150.0)
        self.assertLess(across_wrap["heading_error_deg"], -150.0)
        self.assertLess(first["x_error_m"], 0.0)
        self.assertLess(across_wrap["x_error_m"], 0.0)

    def test_progress_never_moves_backward(self):
        guidance = PathGuidance()
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.0), 0.0, (1.0, 0.0)
        )
        forward = guidance.update((0.32, 0.0), 0.5, allow_course_update=False)
        backward = guidance.update((0.12, 0.0), 0.6, allow_course_update=False)
        self.assertGreaterEqual(backward["along_m"], forward["along_m"])

    def test_structured_frenet_state_and_command_preserve_legacy_outputs(self):
        guidance = PathGuidance()
        result = guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.05), 0.0, (1.0, 0.0)
        )

        frenet = result["frenet"]
        command = result["command"]
        self.assertAlmostEqual(frenet["s_m"], result["along_m"])
        self.assertAlmostEqual(
            frenet["f_m"], result["signed_cross_track_error_m"]
        )
        self.assertIn("s_dot_mps", frenet)
        self.assertIn("f_dot_mps", frenet)
        self.assertIn("yaw_rate_rps", frenet)
        self.assertAlmostEqual(
            frenet["heading_error_deg"], result["heading_error_deg"]
        )
        self.assertAlmostEqual(
            frenet["curvature_per_m"], result["path_curvature_per_m"]
        )
        self.assertAlmostEqual(command["turn_demand"], result["steering_demand"])
        self.assertAlmostEqual(
            command["protocol_x_error_m"], result["x_error_m"]
        )
        self.assertAlmostEqual(
            command["drive_distance_m"], result["drive_distance_m"]
        )
        self.assertAlmostEqual(
            command["desired_yaw_rate_rps"], result["desired_yaw_rate_rps"]
        )

    def test_frenet_rates_are_reported_in_path_frame(self):
        guidance = PathGuidance(cross_track_rate_gain=0.20)
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)],
            position=(0.0, 0.0),
            timestamp=0.0,
            initial_heading=(math.cos(math.radians(30.0)), math.sin(math.radians(30.0))),
        )
        # With no course update the supplied speed is projected through the
        # current body heading and path tangent.
        result = guidance.update(
            (0.0, 0.0), 0.1, allow_course_update=False, speed_mps=0.2
        )
        self.assertAlmostEqual(result["s_dot_mps"], 0.2 * math.cos(math.radians(30.0)), places=6)
        self.assertAlmostEqual(result["f_dot_mps"], 0.2 * math.sin(math.radians(30.0)), places=6)
        self.assertLess(
            result["desired_yaw_rate_rps"], result["yaw_rate_scale_rps"]
        )
        self.assertAlmostEqual(result["frenet"]["s_m"], result["s_m"])
        self.assertAlmostEqual(result["frenet"]["f_m"], result["f_m"])

    def test_off_path_distance_shortens_lookahead_and_adds_cross_feedback(self):
        guidance = PathGuidance(
            lookahead_m=0.24,
            min_lookahead_m=0.10,
            full_attraction_error_m=0.12,
        )
        result = guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.0), 0.0, (1.0, 0.0)
        )
        self.assertAlmostEqual(result["lookahead_m"], 0.24)
        np.testing.assert_allclose(result["lookahead_point"], [0.24, 0.0])

        halfway = guidance.update(
            (0.10, 0.06), 0.1, allow_course_update=False
        )
        self.assertAlmostEqual(halfway["lookahead_m"], 0.17)
        self.assertGreater(halfway["cross_track_feedback"], 0.0)

        far = guidance.update(
            (0.10, 0.12), 0.2, allow_course_update=False
        )
        self.assertAlmostEqual(far["lookahead_m"], 0.10)
        self.assertAlmostEqual(far["off_path_ratio"], 1.0)
        self.assertGreater(far["x_error_m"], 0.0)
        self.assertGreater(far["control_severity"], 0.4)

    def test_corner_shortens_lookahead_before_fish_leaves_path(self):
        guidance = PathGuidance(lookahead_m=0.15)
        guidance.start(
            [(0.0, 0.0), (0.30, 0.0), (0.30, -0.50)],
            (0.20, 0.0), 0.0, (1.0, 0.0),
        )
        result = guidance.update((0.20, 0.0), 0.1, allow_course_update=False)
        self.assertLess(result["lookahead_m"], 0.15)
        self.assertEqual(result["curve_direction"], "LEFT")
        self.assertGreater(result["curve_feedforward"], 0.0)
        self.assertGreater(result["x_error_m"], 0.0)

    def test_curve_preview_reports_left_right_and_straight(self):
        left = PathGuidance().start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, -0.50)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        self.assertEqual(left["curve_direction"], "LEFT")
        self.assertGreater(left["path_curve_angle_deg"], 0.0)
        self.assertGreater(left["path_curvature_per_m"], 0.0)
        self.assertGreater(left["curve_feedforward"], 0.0)

        right = PathGuidance().start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, 0.50)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        self.assertEqual(right["curve_direction"], "RIGHT")
        self.assertLess(right["path_curve_angle_deg"], 0.0)
        self.assertLess(right["path_curvature_per_m"], 0.0)
        self.assertLess(right["curve_feedforward"], 0.0)

        straight = PathGuidance().start(
            [(0.0, 0.0), (1.0, 0.0)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        self.assertEqual(straight["curve_direction"], "STRAIGHT")
        self.assertAlmostEqual(straight["path_curve_severity"], 0.0)
        self.assertAlmostEqual(straight["curve_feedforward"], 0.0)

    def test_upcoming_curve_reduces_propeller_before_large_heading_error(self):
        result = PathGuidance().start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, -0.50)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        self.assertAlmostEqual(result["heading_error_deg"], 0.0, places=6)
        self.assertGreater(result["path_curve_severity"], 0.0)
        self.assertGreater(result["curve_severity"], 0.0)
        self.assertLess(result["lookahead_m"], 0.24)
        self.assertGreater(result["x_error_m"], 0.0)

    def test_off_path_ratio_no_longer_forces_full_turn_when_aligned(self):
        position = np.asarray([0.0, 0.30])
        return_heading = np.asarray([0.10, -0.30])
        return_heading /= np.linalg.norm(return_heading)
        result = PathGuidance().start(
            [(0.0, 0.0), (1.0, 0.0)],
            position, 0.0, return_heading,
        )
        self.assertAlmostEqual(result["off_path_ratio"], 1.0)
        self.assertLess(result["tangent_heading_error_deg"], 0.0)
        self.assertGreater(result["los_angle_deg"], 0.0)
        self.assertGreater(result["cross_track_feedback"], 0.0)
        self.assertAlmostEqual(result["heading_feedback"], 0.0, places=6)
        self.assertAlmostEqual(result["x_error_m"], 0.0, places=6)
        self.assertAlmostEqual(result["control_severity"], 0.0, places=6)
        self.assertAlmostEqual(result["curve_severity"], 0.0, places=6)

    def test_small_straight_heading_error_has_direct_geometric_feedback(self):
        heading_angle = math.radians(5.0)
        result = PathGuidance().start(
            [(0.0, 0.0), (1.0, 0.0)],
            (0.0, 0.0), 0.0,
            (math.cos(heading_angle), math.sin(heading_angle)),
        )
        self.assertAlmostEqual(result["path_curve_severity"], 0.0)
        self.assertAlmostEqual(result["heading_feedback"], 5.0 / 90.0)
        self.assertAlmostEqual(result["cross_track_feedback"], 0.0)
        self.assertAlmostEqual(
            result["x_error_m"], result["max_x_error_m"] * 5.0 / 90.0
        )

    def test_total_turn_uses_curve_plus_unified_los_heading_feedback(self):
        result = PathGuidance().start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, -0.50)],
            (0.0, 0.03), 0.0,
            (math.cos(math.radians(10.0)), math.sin(math.radians(10.0))),
        )
        expected = np.clip(
            result["curve_feedforward"]
            + result["heading_feedback"],
            -1.0,
            1.0,
        )
        expected_los_error_deg = (
            result["tangent_heading_error_deg"] + result["los_angle_deg"]
        )
        self.assertAlmostEqual(
            result["heading_error_deg"], expected_los_error_deg
        )
        self.assertAlmostEqual(result["steering_demand"], expected)
        self.assertAlmostEqual(
            result["x_error_m"], expected * result["max_x_error_m"]
        )

    def test_los_combines_large_tangent_and_cross_errors_before_saturation(self):
        heading_angle = math.radians(120.0)
        result = PathGuidance(
            lookahead_m=0.10,
            min_lookahead_m=0.10,
        ).start(
            [(0.0, 0.0), (1.0, 0.0)],
            (0.0, -math.sqrt(3.0) * 0.10),
            0.0,
            (math.cos(heading_angle), math.sin(heading_angle)),
        )

        self.assertAlmostEqual(
            result["tangent_heading_error_deg"], 120.0, places=6
        )
        self.assertAlmostEqual(result["los_angle_deg"], -60.0, places=6)
        self.assertAlmostEqual(result["heading_error_deg"], 60.0, places=6)
        self.assertAlmostEqual(result["heading_feedback"], 2.0 / 3.0, places=6)
        self.assertAlmostEqual(result["steering_demand"], 2.0 / 3.0, places=6)

    def test_low_curve_large_heading_error_reaches_full_turn(self):
        heading_angle = math.radians(90.0)
        result = PathGuidance().start(
            [(0.0, 0.0), (1.0, 0.0)],
            (0.0, 0.0), 0.0,
            (math.cos(heading_angle), math.sin(heading_angle)),
        )
        self.assertAlmostEqual(result["path_curve_severity"], 0.0)
        self.assertAlmostEqual(result["heading_feedback"], 1.0)
        self.assertAlmostEqual(
            abs(result["x_error_m"]), result["max_x_error_m"]
        )

    def test_rough_040_m_circle_sets_5_per_m_reference_curvature(self):
        guidance = PathGuidance()
        self.assertAlmostEqual(guidance.estimated_min_turn_radius_m, 0.20)
        self.assertAlmostEqual(guidance.max_path_curvature_per_m, 5.0)

    def test_curve_feedforward_uses_independent_measured_turn_radii(self):
        left = PathGuidance(
            estimated_min_turn_radius_m=0.20,
            left_turn_radius_m=0.16,
            right_turn_radius_m=0.27,
        ).start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, -0.50)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        right = PathGuidance(
            estimated_min_turn_radius_m=0.20,
            left_turn_radius_m=0.16,
            right_turn_radius_m=0.27,
        ).start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, 0.50)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        self.assertEqual(left["turn_radius_source"], "MEASURED_LEFT")
        self.assertAlmostEqual(left["turn_radius_m"], 0.16)
        self.assertEqual(right["turn_radius_source"], "MEASURED_RIGHT")
        self.assertAlmostEqual(right["turn_radius_m"], 0.27)
        self.assertAlmostEqual(
            left["curve_feedforward"],
            left["path_curvature_per_m"] * 0.16,
        )
        self.assertAlmostEqual(
            right["curve_feedforward"],
            right["path_curvature_per_m"] * 0.27,
        )

    def test_steering_limit_is_exact_full_scale_for_300_percent_per_m(self):
        result = PathGuidance().start(
            [(0.0, 0.0), (1.0, 0.0)],
            (0.0, 0.0), 0.0, (-1.0, 0.0),
        )
        self.assertAlmostEqual(result["max_x_error_m"], 1.0 / 3.0, places=6)
        self.assertAlmostEqual(result["x_error_m"], 1.0 / 3.0, places=6)
        self.assertLessEqual(abs(result["x_error_m"]), result["max_x_error_m"])

    def test_power_mixing_severity_matches_actual_total_turn_demand(self):
        result = PathGuidance().start(
            [(0.0, 0.0), (0.28, 0.0), (0.28, -0.50)],
            (0.0, 0.0), 0.0, (1.0, 0.0),
        )
        self.assertAlmostEqual(
            result["curve_severity"], abs(result["steering_demand"])
        )

    def test_terminal_brake_and_stop_use_only_fixed_distance(self):
        guidance = PathGuidance(
            lookahead_m=0.15,
            arrival_radius_m=0.22,
            brake_radius_m=0.35,
        )
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.0), 0.0, (1.0, 0.0)
        )
        guidance.update((0.40, 0.0), 0.5, allow_course_update=False)
        braking = guidance.update(
            (0.66, 0.0), 1.0, allow_course_update=False, speed_mps=0.01
        )
        self.assertTrue(braking["brake_request"])
        self.assertFalse(braking["settled"])
        self.assertAlmostEqual(braking["brake_distance_m"], 0.35)

        stopped = guidance.update(
            (0.79, 0.0), 1.2, allow_course_update=False, speed_mps=1.0
        )
        self.assertFalse(stopped["brake_request"])
        self.assertTrue(stopped["settled"])

    def test_default_terminal_brake_starts_at_040_m(self):
        guidance = PathGuidance()
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.0), 0.0, (1.0, 0.0)
        )
        guidance.update(
            (0.40, 0.0), 0.5, allow_course_update=False, speed_mps=0.25
        )
        result = guidance.update(
            (0.61, 0.0), 1.0, allow_course_update=False, speed_mps=0.25
        )
        self.assertTrue(result["brake_request"])
        self.assertAlmostEqual(result["brake_distance_m"], 0.40)

    def test_default_arrival_uses_020_m_stop_circle(self):
        guidance = PathGuidance()
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.0), 0.0, (1.0, 0.0)
        )
        guidance.update((0.40, 0.0), 0.5, allow_course_update=False)
        result = guidance.update((0.81, 0.0), 1.0, allow_course_update=False)
        self.assertTrue(result["arrived"])
        self.assertFalse(result["brake_request"])

    def test_arrival_also_checks_endpoint_distance(self):
        guidance = PathGuidance(arrival_radius_m=0.22)
        guidance.start(
            [(0.0, 0.0), (1.0, 0.0)], (0.0, 0.0), 0.0, (1.0, 0.0)
        )
        guidance.update((0.40, 0.0), 0.4, allow_course_update=False)
        guidance.update((0.80, 0.0), 0.8, allow_course_update=False)
        result = guidance.update((1.0, 0.50), 1.0, allow_course_update=False)
        self.assertAlmostEqual(result["dist_m"], 0.0, places=6)
        self.assertAlmostEqual(result["end_distance_m"], 0.50, places=6)
        self.assertFalse(result["arrived"])

    def test_loop_path_does_not_arrive_before_final_progress(self):
        guidance = PathGuidance(arrival_radius_m=0.22)
        result = guidance.start(
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.05, 0.0)],
            position=(0.0, 0.0),
            timestamp=0.0,
            initial_heading=(1.0, 0.0),
        )
        self.assertLess(result["end_distance_m"], 0.22)
        self.assertGreater(result["dist_m"], 0.22)
        self.assertFalse(result["arrived"])

    def test_heading_estimator_holds_when_slow_then_follows_course(self):
        estimator = HeadingEstimator(blend=0.5)
        estimator.reset((1.0, 0.0), (0.0, 0.0), 0.0)
        heading, source = estimator.update((0.005, 0.0), 0.3)
        np.testing.assert_allclose(heading, [1.0, 0.0])
        self.assertEqual(source, "INITIAL")

        estimator.update((0.04, 0.04), 0.45)
        heading, source = estimator.update((0.08, 0.08), 0.6)
        self.assertEqual(source, "COURSE")
        self.assertGreater(heading[1], 0.0)
        self.assertAlmostEqual(float(np.linalg.norm(heading)), 1.0, places=6)

    def test_heading_estimator_rejects_180_degree_jump(self):
        estimator = HeadingEstimator()
        estimator.reset((1.0, 0.0), (0.0, 0.0), 0.0)
        estimator.update((-0.10, 0.0), 0.15)
        heading, source = estimator.update((-0.20, 0.0), 0.30)
        np.testing.assert_allclose(heading, [1.0, 0.0])
        self.assertEqual(source, "INITIAL")

    def test_heading_estimator_can_follow_a_real_turn_past_90_degrees(self):
        estimator = HeadingEstimator(blend=0.5)
        course = np.asarray([-0.5, math.sqrt(3.0) / 2.0])
        estimator.reset((1.0, 0.0), (0.0, 0.0), 0.0)
        estimator.update(course * 0.05, 0.15)
        heading, source = estimator.update(course * 0.10, 0.30)
        self.assertEqual(source, "COURSE")
        self.assertGreater(heading[1], 0.0)

    def test_default_heading_filter_does_not_follow_tail_swing_in_one_step(self):
        estimator = HeadingEstimator()
        estimator.reset((1.0, 0.0), (0.0, 0.0), 0.0)
        estimator.update((0.0, 0.03), 0.15)
        heading, source = estimator.update((0.0, 0.06), 0.30)
        self.assertEqual(source, "COURSE")
        heading_angle_deg = math.degrees(math.atan2(heading[1], heading[0]))
        self.assertGreater(heading_angle_deg, 0.0)
        self.assertLess(heading_angle_deg, 20.0)

    def test_velocity_estimator_rejects_impossible_marker_spike(self):
        estimator = VelocityEstimator(
            history_seconds=0.40,
            min_span_seconds=0.10,
            blend=1.0,
            max_speed_mps=0.80,
        )
        estimator.reset((0.0, 0.0), 0.0)
        estimator.update((0.03, 0.0), 0.10)
        velocity = estimator.update((0.06, 0.0), 0.20)
        np.testing.assert_allclose(velocity, [0.30, 0.0], atol=1e-6)

        rejected = estimator.update((2.0, 2.0), 0.30)
        np.testing.assert_allclose(rejected, velocity, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
