import os
import sys
import unittest

import cv2
import numpy as np


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VISION_DIR = os.path.join(PROJECT_DIR, "VISION")
RUNTIME_DIR = os.path.join(VISION_DIR, "runtime")
if RUNTIME_DIR not in sys.path:
    sys.path.insert(0, RUNTIME_DIR)

from perception import (  # noqa: E402
    FixedReferenceTracker,
    MarkerProfile,
    MarkerTrackerConfig,
    ReferenceSource,
)


FRAME_SIZE = (240, 320)
MARKER_BGR = (0, 180, 255)


def make_frame(marker=(160, 120), visible=True, fish_angle=0.0, second_blob=None):
    height, width = FRAME_SIZE
    image = np.full((height, width, 3), (150, 100, 50), dtype=np.uint8)
    centre = (int(marker[0]), int(marker[1]))
    cv2.ellipse(image, centre, (70, 24), fish_angle, 0, 360, (165, 165, 165), -1)
    if visible:
        cv2.circle(image, centre, 10, MARKER_BGR, -1, cv2.LINE_AA)
    if second_blob is not None:
        cv2.circle(image, tuple(second_blob), 10, MARKER_BGR, -1, cv2.LINE_AA)
    return image


def make_rigid_frame(marker=(105, 120), body=(175, 120), body_visible=True):
    height, width = FRAME_SIZE
    image = np.full((height, width, 3), (150, 100, 50), dtype=np.uint8)
    if body_visible:
        cv2.ellipse(image, tuple(body), (34, 18), 0, 0, 360, (235, 235, 235), -1)
    cv2.circle(image, tuple(marker), 10, MARKER_BGR, -1, cv2.LINE_AA)
    return image


class FixedReferenceTrackerTests(unittest.TestCase):
    def make_tracker(self):
        tracker = FixedReferenceTracker(
            config=MarkerTrackerConfig(
                prediction_horizon_s=0.15,
                reacquire_after_s=0.20,
            )
        )
        sample = make_frame()
        tracker.calibrate_from_roi(sample, (144, 104, 177, 137), save=False)
        return tracker

    def test_unprofiled_yolo_is_explicit_fallback(self):
        tracker = FixedReferenceTracker()
        result = tracker.update(
            make_frame(), 1.0, (80, 80, 240, 160), 0.9, track_id=7
        )
        self.assertEqual(result.source, ReferenceSource.ESTIMATED_FALLBACK)
        self.assertEqual(result.position, (160.0, 120.0))
        self.assertFalse(result.usable_for_pwm_speed)

    def test_yolo_box_changes_do_not_move_marker_reference(self):
        tracker = self.make_tracker()
        boxes = [
            (70, 75, 250, 165),
            (120, 95, 205, 150),
            (20, 35, 300, 205),
        ]
        positions = []
        for index, box in enumerate(boxes):
            result = tracker.update(
                make_frame(), 1.0 + index * 0.04, box, 0.95, track_id=3
            )
            self.assertEqual(result.source, ReferenceSource.MARKER)
            positions.append(result.position)
        for position in positions:
            self.assertLess(np.linalg.norm(np.asarray(position) - (160.0, 120.0)), 0.8)

    def test_white_front_body_becomes_the_control_reference(self):
        tracker = FixedReferenceTracker()
        frame = make_rigid_frame()
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        result = tracker.update(
            frame, 1.0, (70, 85, 220, 155), 0.95, track_id=11
        )
        self.assertEqual(result.source, ReferenceSource.RIGID_BODY)
        self.assertTrue(result.usable_for_pwm_speed)
        self.assertLess(
            np.linalg.norm(np.asarray(result.position) - (175.0, 120.0)), 1.0
        )
        self.assertLess(
            np.linalg.norm(
                np.asarray(result.metrics["tail_marker_position"])
                - (105.0, 120.0)
            ),
            1.0,
        )

    def test_rigid_body_can_be_disabled_for_simple_tail_tracking(self):
        tracker = FixedReferenceTracker(enable_rigid_body=False)
        frame = make_rigid_frame()
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        result = tracker.update(
            frame, 1.0, (70, 85, 220, 155), 0.95, track_id=11
        )
        self.assertEqual(result.source, ReferenceSource.MARKER)
        self.assertLess(
            np.linalg.norm(np.asarray(result.position) - (105.0, 120.0)), 1.0
        )

    def test_rigid_body_short_dropout_predicts_body_not_tail(self):
        tracker = FixedReferenceTracker(
            config=MarkerTrackerConfig(prediction_horizon_s=0.15)
        )
        frame = make_rigid_frame()
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        tracker.update(frame, 2.0, (70, 85, 220, 155), 0.95, track_id=12)
        result = tracker.update(
            make_rigid_frame(body_visible=False),
            2.05,
            (70, 85, 220, 155),
            0.95,
            track_id=12,
        )
        self.assertEqual(result.source, ReferenceSource.PREDICTED)
        self.assertGreater(result.position[0], 150.0)
        self.assertEqual(result.metrics["reference_role"], "RIGID_WHITE_BODY")

    def test_small_white_reflection_is_rejected_by_area_gate(self):
        tracker = FixedReferenceTracker()
        frame = make_rigid_frame(body_visible=False)
        cv2.circle(frame, (175, 120), 5, (235, 235, 235), -1)
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        result = tracker.update(
            frame, 2.5, (70, 85, 220, 155), 0.95, track_id=13
        )
        self.assertEqual(result.source, ReferenceSource.MARKER)
        self.assertIn("BODY_TOO_SMALL_GATE", result.gate_reasons)

    def test_round_white_glare_is_not_accepted_as_rigid_body(self):
        tracker = FixedReferenceTracker()
        frame = make_rigid_frame(body_visible=False)
        cv2.circle(frame, (175, 120), 16, (235, 235, 235), -1)
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        result = tracker.update(
            frame, 2.7, (70, 85, 220, 155), 0.95, track_id=14
        )
        self.assertEqual(result.source, ReferenceSource.MARKER)
        self.assertIn("BODY_GLARE_SHAPE_GATE", result.gate_reasons)

    def test_overexposed_elongated_glare_is_rejected(self):
        tracker = FixedReferenceTracker()
        frame = make_rigid_frame(body_visible=False)
        cv2.ellipse(frame, (175, 120), (34, 18), 0, 0, 360, (255, 255, 255), -1)
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        result = tracker.update(
            frame, 2.9, (70, 85, 220, 155), 0.95, track_id=15
        )
        self.assertEqual(result.source, ReferenceSource.MARKER)
        self.assertIn("BODY_GLARE_EXPOSURE_GATE", result.gate_reasons)

    def test_head_click_seed_accepts_real_round_overexposed_body(self):
        tracker = FixedReferenceTracker()
        frame = make_rigid_frame(body_visible=False)
        cv2.circle(frame, (175, 120), 16, (255, 255, 255), -1)
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        tracker.seed_rigid_body((175, 120), 3.0, (105, 120))
        result = tracker.update(
            frame, 3.02, (70, 85, 220, 155), 0.95, track_id=16
        )
        self.assertEqual(result.source, ReferenceSource.RIGID_BODY)
        self.assertLess(
            np.linalg.norm(np.asarray(result.position) - (175.0, 120.0)), 1.0
        )

    def test_head_click_seed_rejects_far_larger_reflection(self):
        tracker = FixedReferenceTracker()
        frame = make_rigid_frame(body_visible=False)
        cv2.circle(frame, (175, 120), 13, (240, 240, 240), -1)
        cv2.circle(frame, (212, 120), 19, (240, 240, 240), -1)
        tracker.calibrate_from_roi(frame, (90, 104, 120, 136), save=False)
        tracker.seed_rigid_body((175, 120), 3.5, (105, 120))
        result = tracker.update(
            frame, 3.52, (70, 85, 240, 155), 0.95, track_id=17
        )
        self.assertEqual(result.source, ReferenceSource.RIGID_BODY)
        self.assertLess(result.position[0], 190.0)

    def test_rotating_fish_body_keeps_fixed_marker_centre(self):
        tracker = self.make_tracker()
        positions = []
        for index, angle in enumerate((0, 30, 60, 90, 135)):
            result = tracker.update(
                make_frame(fish_angle=angle),
                2.0 + index * 0.04,
                (65, 70, 255, 170),
                0.93,
                track_id=2,
            )
            self.assertEqual(result.source, ReferenceSource.MARKER)
            positions.append(result.position)
        drift = max(
            np.linalg.norm(np.asarray(position) - np.asarray(positions[0]))
            for position in positions
        )
        self.assertLess(drift, 0.8)

    def test_position_jump_candidate_is_rejected(self):
        tracker = self.make_tracker()
        first = tracker.update(make_frame(), 3.0, (60, 60, 260, 180), 0.95, 9)
        self.assertEqual(first.source, ReferenceSource.MARKER)
        jumped = tracker.update(
            make_frame(marker=(250, 120)),
            3.04,
            (50, 55, 285, 185),
            0.95,
            9,
        )
        self.assertEqual(jumped.source, ReferenceSource.PREDICTED)
        self.assertIn("POSITION_JUMP_GATE", jumped.gate_reasons)
        self.assertLess(np.linalg.norm(np.asarray(jumped.position) - (160.0, 120.0)), 1.0)

    def test_occlusion_predicts_briefly_then_becomes_invalid(self):
        tracker = self.make_tracker()
        tracker.update(make_frame(), 4.0, (60, 60, 260, 180), 0.95, 5)
        brief = tracker.update(
            make_frame(visible=False), 4.05, (60, 60, 260, 180), 0.95, 5
        )
        expired = tracker.update(
            make_frame(visible=False), 4.22, (60, 60, 260, 180), 0.95, 5
        )
        self.assertEqual(brief.source, ReferenceSource.PREDICTED)
        self.assertFalse(brief.usable_for_pwm_speed)
        self.assertEqual(expired.source, ReferenceSource.INVALID)
        self.assertIsNone(expired.position)

    def test_yolo_reacquires_marker_after_occlusion(self):
        tracker = self.make_tracker()
        tracker.update(make_frame(), 5.0, (60, 60, 260, 180), 0.95, 4)
        tracker.update(make_frame(visible=False), 5.30, (60, 60, 260, 180), 0.95, 4)
        reacquired = tracker.update(
            make_frame(marker=(220, 120)),
            5.34,
            (145, 75, 295, 170),
            0.96,
            4,
        )
        self.assertEqual(reacquired.source, ReferenceSource.MARKER)
        self.assertLess(np.linalg.norm(np.asarray(reacquired.position) - (220.0, 120.0)), 0.8)

    def test_marker_keeps_tracking_after_yolo_hold_expires(self):
        tracker = self.make_tracker()
        tracker.update(make_frame(), 5.0, (60, 60, 260, 180), 0.95, 4)
        result = tracker.update(
            make_frame(marker=(166, 120)),
            6.00,
            yolo_bbox=None,
            yolo_confidence=0.0,
            track_id=None,
        )
        self.assertEqual(result.source, ReferenceSource.MARKER)
        self.assertFalse(result.yolo_confirmed)
        self.assertLess(
            np.linalg.norm(np.asarray(result.position) - (166.0, 120.0)), 0.8
        )

    def test_marker_prediction_does_not_require_yolo(self):
        tracker = self.make_tracker()
        tracker.config.yolo_hold_s = 0.05
        tracker.update(make_frame(), 5.0, (60, 60, 260, 180), 0.95, 4)
        tracker.update(
            make_frame(marker=(164, 120)), 5.08, (60, 60, 260, 180), 0.95, 4
        )
        result = tracker.update(
            make_frame(visible=False),
            5.18,
            yolo_bbox=None,
            yolo_confidence=0.0,
            track_id=None,
        )
        self.assertEqual(result.source, ReferenceSource.PREDICTED)
        self.assertFalse(result.yolo_confirmed)

    def test_marker_clipped_by_search_boundary_is_rejected(self):
        tracker = self.make_tracker()
        result = tracker.update(
            make_frame(marker=(3, 120)),
            6.0,
            (0, 100, 60, 145),
            0.95,
            8,
        )
        self.assertEqual(result.source, ReferenceSource.INVALID)
        self.assertIn("BOUNDARY_CROP_GATE", result.gate_reasons)

    def test_profile_round_trip(self):
        path = os.path.join(VISION_DIR, "configs", ".marker_profile.test.json")
        try:
            tracker = FixedReferenceTracker(profile_path=path)
            tracker.calibrate_from_roi(
                make_frame(), (144, 104, 177, 137), save=True
            )
            loaded = FixedReferenceTracker(profile_path=path)
            self.assertTrue(loaded.is_profiled)
            self.assertAlmostEqual(
                loaded.profile.hue_center, tracker.profile.hue_center, places=5
            )
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_loose_roi_auto_finds_orange_tail_centre(self):
        tracker = FixedReferenceTracker()
        profile = tracker.calibrate_from_roi(
            make_frame(), (90, 80, 230, 160), save=False
        )
        self.assertLess(profile.sample_roi_size[0], 30)
        self.assertLess(profile.sample_roi_size[1], 30)
        centre = tracker.last_calibration["marker_center"]
        self.assertLess(np.linalg.norm(np.asarray(centre) - (160.0, 120.0)), 0.8)


    def test_low_saturation_fragmented_legacy_profile_is_rejected(self):
        tracker = FixedReferenceTracker()
        bad_profile = MarkerProfile(
            sat_min=5,
            expected_area=924.5,
            expected_circularity=0.216,
            expected_extent=0.390,
            expected_aspect=1.73,
            sample_roi_size=(90, 54),
        )
        errors = tracker.profile_validation_errors(bad_profile)
        self.assertGreaterEqual(len(errors), 2)
        self.assertTrue(any("饱和度" in error for error in errors))
        self.assertTrue(any("ROI" in error for error in errors))


if __name__ == "__main__":
    unittest.main()

