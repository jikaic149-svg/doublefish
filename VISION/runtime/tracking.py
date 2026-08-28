"""Class-aware fixed-point tracking with a small, dependency-free EKF.

The live detector only supplies sparse bounding boxes.  This module turns each
box into a repeatable point inside the fish body and predicts that point between
detector updates.  The tracker deliberately reports a *course* state only as an
internal model value; callers may use the position result without treating the
axis-aligned box as a fish-pose measurement.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np


CLASS_NAMES = {0: "red_fish", 1: "blue_fish"}
DEFAULT_ANCHOR = (0.5, 0.5)


def _wrap_angle(angle: float) -> float:
    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def _angle_delta(left: float, right: float) -> float:
    return _wrap_angle(float(left) - float(right))


def _clip_anchor(value: float) -> float:
    return float(np.clip(float(value), 0.0, 1.0))


def _iou(left: Sequence[float], right: Sequence[float]) -> float:
    lx1, ly1, lx2, ly2 = [float(v) for v in left]
    rx1, ry1, rx2, ry2 = [float(v) for v in right]
    intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(
        0.0, min(ly2, ry2) - max(ly1, ry1)
    )
    left_area = max(0.0, lx2 - lx1) * max(0.0, ly2 - ly1)
    right_area = max(0.0, rx2 - rx1) * max(0.0, ry2 - ry1)
    union = left_area + right_area - intersection
    return intersection / union if union > 1e-9 else 0.0


@dataclass(frozen=True)
class FishDetection:
    """One detector observation in image coordinates."""

    class_id: int
    class_name: str
    bbox: tuple[float, float, float, float]
    confidence: float
    timestamp: float
    track_id: Optional[int] = None

    @property
    def width(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])

    @property
    def aspect(self) -> float:
        short = max(1e-6, min(self.width, self.height))
        return max(self.width, self.height) / short

    @property
    def area(self) -> float:
        return self.width * self.height

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], timestamp: Optional[float] = None):
        class_id = int(value.get("class_id", value.get("cls", -1)))
        class_name = CLASS_NAMES.get(class_id, str(value.get("class_name") or "unknown"))
        raw_bbox = value.get("bbox") or value.get("xyxy")
        if raw_bbox is None or len(raw_bbox) != 4:
            raise ValueError("detection bbox must contain four coordinates")
        stamp = value.get("timestamp", value.get("frame_time", timestamp))
        if stamp is None:
            raise ValueError("detection timestamp is required")
        return cls(
            class_id=class_id,
            class_name=class_name,
            bbox=tuple(float(v) for v in raw_bbox),
            confidence=float(value.get("confidence", value.get("conf", 0.0))),
            timestamp=float(stamp),
            track_id=(int(value["track_id"]) if value.get("track_id") is not None else None),
        )

    def anchor(self, ratio: Sequence[float] = DEFAULT_ANCHOR) -> tuple[float, float]:
        alpha, beta = _clip_anchor(ratio[0]), _clip_anchor(ratio[1])
        return (
            float(self.bbox[0] + alpha * self.width),
            float(self.bbox[1] + beta * self.height),
        )

    def to_dict(self, anchor_ratio: Sequence[float] = DEFAULT_ANCHOR) -> dict[str, Any]:
        point = self.anchor(anchor_ratio)
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "bbox": [float(v) for v in self.bbox],
            "confidence": float(self.confidence),
            "timestamp": float(self.timestamp),
            "width": float(self.width),
            "height": float(self.height),
            "aspect": float(self.aspect),
            "anchor_pixel": [float(point[0]), float(point[1])],
            "track_id": self.track_id,
        }


def deduplicate_detections(
    detections: Iterable[FishDetection | Mapping[str, Any]],
    *,
    same_class_iou: float = 0.50,
    max_per_class: int = 1,
) -> list[FishDetection]:
    """Keep one temporally usable candidate per known class.

    Ultralytics can return several overlapping boxes for the low-contrast blue
    fish.  Class-wise suppression is intentional: red and blue boxes must never
    suppress one another.
    """

    parsed: list[FishDetection] = []
    for item in detections:
        detection = item if isinstance(item, FishDetection) else FishDetection.from_mapping(item)
        if detection.class_id not in CLASS_NAMES:
            continue
        if detection.width <= 0.0 or detection.height <= 0.0:
            continue
        parsed.append(detection)

    selected: list[FishDetection] = []
    for class_id in sorted(CLASS_NAMES):
        ordered = sorted(
            (item for item in parsed if item.class_id == class_id),
            key=lambda item: item.confidence,
            reverse=True,
        )
        kept: list[FishDetection] = []
        for item in ordered:
            if any(_iou(item.bbox, previous.bbox) >= same_class_iou for previous in kept):
                continue
            kept.append(item)
            if len(kept) >= max(1, int(max_per_class)):
                break
        selected.extend(kept)
    return selected


@dataclass
class EKFConfig:
    """Tuning values shared by pixel and calibrated-world trackers."""

    max_prediction_s: float = 0.45
    mahalanobis_gate: float = 9.21
    # Pixel-mode default.  The calibrated world pipeline can supply its own
    # metre/second limit; 800 px/s is a conservative bound for the 1920x1080
    # recordings and prevents a false box from teleporting a track.
    max_speed: float = 800.0
    speed_process_std: float = 180.0
    yaw_acceleration_process_std: float = 6.0
    base_measurement_sigma: float = 3.0
    min_measurement_sigma: float = 3.0
    max_measurement_sigma: float = 20.0
    posture_noise_scale: float = 0.80
    confidence_floor: float = 0.15
    covariance_limit: float = 2500.0
    # Output-only deadband for pixel tracks.  The EKF state still moves inside
    # this radius; only the reported point is held to suppress bbox shimmer.
    output_deadband: float = 2.5
    min_motion_dt: float = 0.02
    max_motion_dt: float = 1.0


@dataclass(frozen=True)
class FishTrackResult:
    class_name: str
    track_id: str
    source: str
    position: Optional[tuple[float, float]]
    predicted_position: Optional[tuple[float, float]]
    bbox: Optional[tuple[float, float, float, float]]
    confidence: float
    quality: float
    covariance: tuple[float, float]
    anchor_ratio: tuple[float, float]
    anchor_quality: float
    detection_age_s: Optional[float]
    prediction_age_s: Optional[float]
    valid: bool
    usable_for_control: bool
    accepted_detection: bool
    gate_reasons: tuple[str, ...] = field(default_factory=tuple)

    # Explicit names used by the structured vision contract.  ``position`` is
    # kept as the backwards-compatible pixel position until homography-aware
    # tracking is enabled in the calibrated pipeline.
    @property
    def position_pixel(self):
        return self.position

    @property
    def position_world(self):
        return None

    @property
    def velocity_world(self):
        return None

    @property
    def speed_mps(self):
        return None

    @property
    def course_heading_deg(self):
        return None

    @property
    def yaw_rate_rps(self):
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_name": self.class_name,
            "track_id": self.track_id,
            "source": self.source,
            "position": list(self.position) if self.position is not None else None,
            "position_pixel": list(self.position_pixel) if self.position_pixel is not None else None,
            "position_world": None,
            "velocity_world": None,
            "speed_mps": None,
            "course_heading_deg": None,
            "yaw_rate_rps": None,
            "predicted_position": (
                list(self.predicted_position) if self.predicted_position is not None else None
            ),
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "confidence": float(self.confidence),
            "quality": float(self.quality),
            "covariance": list(self.covariance),
            "anchor_ratio": list(self.anchor_ratio),
            "anchor_quality": float(self.anchor_quality),
            "detection_age_s": self.detection_age_s,
            "prediction_age_s": self.prediction_age_s,
            "valid": self.valid,
            "usable_for_control": self.usable_for_control,
            "accepted_detection": self.accepted_detection,
            "gate_reasons": list(self.gate_reasons),
        }


class ExtendedKalmanFishTracker:
    """Constant-turn-rate EKF for one class-keyed fish track.

    The internal state is ``[x, y, speed, heading, yaw_rate]``.  Position is
    deliberately the only detector measurement; velocity and heading emerge
    from consecutive accepted point observations and are not interpreted as
    body-pose measurements.
    """

    STATE_SIZE = 5

    def __init__(
        self,
        class_name: str,
        *,
        anchor_ratio: Sequence[float] = DEFAULT_ANCHOR,
        config: Optional[EKFConfig] = None,
    ):
        self.class_name = str(class_name)
        self.track_id = self.class_name
        self.config = config or EKFConfig()
        self.anchor_ratio = (_clip_anchor(anchor_ratio[0]), _clip_anchor(anchor_ratio[1]))
        self.state: Optional[np.ndarray] = None
        self.covariance: Optional[np.ndarray] = None
        self.state_time: Optional[float] = None
        self.last_detection_time: Optional[float] = None
        self.last_bbox: Optional[tuple[float, float, float, float]] = None
        self.last_confidence = 0.0
        self.last_anchor: Optional[np.ndarray] = None
        self.last_aspect: Optional[float] = None
        self.accepted_count = 0
        self.rejected_count = 0
        self.last_gate_reasons: tuple[str, ...] = ()
        self._measurement_history: list[tuple[float, np.ndarray]] = []
        self._last_output_position: Optional[np.ndarray] = None

    def reset(self) -> None:
        self.state = None
        self.covariance = None
        self.state_time = None
        self.last_detection_time = None
        self.last_bbox = None
        self.last_confidence = 0.0
        self.last_anchor = None
        self.last_aspect = None
        self.accepted_count = 0
        self.rejected_count = 0
        self.last_gate_reasons = ()
        self._measurement_history = []
        self._last_output_position = None

    def set_anchor(self, alpha: float, beta: float) -> None:
        self.anchor_ratio = (_clip_anchor(alpha), _clip_anchor(beta))

    @staticmethod
    def _ctrv_step(state: np.ndarray, dt: float) -> np.ndarray:
        result = np.asarray(state, dtype=np.float64).copy()
        if dt <= 0.0:
            return result
        x, y, speed, heading, yaw_rate = result
        turn = float(yaw_rate * dt)
        if abs(yaw_rate) < 1e-5:
            result[0] = x + speed * math.cos(heading) * dt
            result[1] = y + speed * math.sin(heading) * dt
        else:
            result[0] = x + speed / yaw_rate * (
                math.sin(heading + turn) - math.sin(heading)
            )
            result[1] = y + speed / yaw_rate * (
                math.cos(heading) - math.cos(heading + turn)
            )
        result[2] = speed
        result[3] = _wrap_angle(heading + turn)
        result[4] = yaw_rate
        return result

    def _jacobian(self, state: np.ndarray, dt: float) -> np.ndarray:
        jacobian = np.zeros((self.STATE_SIZE, self.STATE_SIZE), dtype=np.float64)
        for index in range(self.STATE_SIZE):
            step = 1e-5 if index in (0, 1, 2, 4) else 1e-6
            plus = np.asarray(state, dtype=np.float64).copy()
            minus = np.asarray(state, dtype=np.float64).copy()
            plus[index] += step
            minus[index] -= step
            plus_value = self._ctrv_step(plus, dt)
            minus_value = self._ctrv_step(minus, dt)
            difference = plus_value - minus_value
            difference[3] = _angle_delta(plus_value[3], minus_value[3])
            jacobian[:, index] = difference / (2.0 * step)
        return jacobian

    def _predict_pair(
        self, state: np.ndarray, covariance: np.ndarray, dt: float
    ) -> tuple[np.ndarray, np.ndarray]:
        if dt <= 0.0:
            return state.copy(), covariance.copy()
        dt = float(min(dt, 2.0))
        predicted = self._ctrv_step(state, dt)
        jacobian = self._jacobian(state, dt)
        q = np.zeros((self.STATE_SIZE, self.STATE_SIZE), dtype=np.float64)
        speed_var = self.config.speed_process_std ** 2 * dt * dt
        yaw_var = self.config.yaw_acceleration_process_std ** 2 * dt * dt
        position_var = 0.25 * speed_var * dt * dt
        q[0, 0] = position_var
        q[1, 1] = position_var
        q[2, 2] = speed_var
        q[3, 3] = yaw_var * dt * dt
        q[4, 4] = yaw_var
        predicted_covariance = jacobian @ covariance @ jacobian.T + q
        predicted_covariance = 0.5 * (predicted_covariance + predicted_covariance.T)
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(predicted_covariance)
            predicted_covariance = (
                eigenvectors
                @ np.diag(np.maximum(eigenvalues, 1e-9))
                @ eigenvectors.T
            )
        except np.linalg.LinAlgError:
            diagonal = np.maximum(np.diag(predicted_covariance), 1e-9)
            predicted_covariance[np.diag_indices(self.STATE_SIZE)] = diagonal
        return predicted, predicted_covariance

    def _measurement_sigma(self, detection: FishDetection) -> float:
        diagonal = math.hypot(detection.width, detection.height)
        sigma = 2.0 + 0.025 * diagonal
        confidence = max(self.config.confidence_floor, min(1.0, detection.confidence))
        sigma *= math.sqrt(0.50 / confidence)
        if self.last_aspect is not None and detection.aspect > 0.0:
            posture_delta = abs(math.log(detection.aspect / max(self.last_aspect, 1e-6)))
            sigma *= 1.0 + min(2.0, self.config.posture_noise_scale * posture_delta)
        return float(np.clip(
            max(self.config.base_measurement_sigma, sigma),
            self.config.min_measurement_sigma,
            self.config.max_measurement_sigma,
        ))

    def _bootstrap_motion(self, point: np.ndarray, timestamp: float) -> None:
        if self.state is None:
            return
        self._measurement_history.append((float(timestamp), point.copy()))
        self._measurement_history = [
            item for item in self._measurement_history
            if timestamp - item[0] <= 0.80
        ]
        if len(self._measurement_history) < 2:
            return
        first_time = self._measurement_history[0][0]
        span = float(timestamp - first_time)
        if span < self.config.min_motion_dt:
            return
        times = np.asarray([item[0] - first_time for item in self._measurement_history], dtype=np.float64)
        points = np.asarray([item[1] for item in self._measurement_history], dtype=np.float64)
        try:
            vx = float(np.polyfit(times, points[:, 0], 1)[0])
            vy = float(np.polyfit(times, points[:, 1], 1)[0])
        except (TypeError, ValueError, np.linalg.LinAlgError):
            return
        displacement = np.asarray([vx, vy], dtype=np.float64)
        speed = float(np.linalg.norm(displacement))
        if speed <= 1e-6:
            return
        speed = min(speed, self.config.max_speed)
        heading = math.atan2(float(displacement[1]), float(displacement[0]))
        previous_heading = float(self.state[3])
        blend = 0.35 if self.accepted_count <= 3 else 0.20
        self.state[2] = (1.0 - blend) * self.state[2] + blend * speed
        self.state[3] = _wrap_angle(
            previous_heading + blend * _angle_delta(heading, previous_heading)
        )
        if self.accepted_count >= 2:
            measured_yaw = _angle_delta(heading, previous_heading) / max(self.config.min_motion_dt, span)
            self.state[4] = 0.85 * self.state[4] + 0.15 * float(
                np.clip(measured_yaw, -20.0, 20.0)
            )

    def update_detection(
        self,
        detection: FishDetection | Mapping[str, Any],
        *,
        measurement: Optional[Sequence[float]] = None,
    ) -> bool:
        item = detection if isinstance(detection, FishDetection) else FishDetection.from_mapping(detection)
        if item.class_name != self.class_name:
            self.last_gate_reasons = ("CLASS_MISMATCH",)
            return False
        timestamp = float(item.timestamp)
        point = np.asarray(measurement if measurement is not None else item.anchor(self.anchor_ratio), dtype=np.float64)
        if point.shape != (2,) or not np.isfinite(point).all():
            self.last_gate_reasons = ("INVALID_ANCHOR",)
            return False

        if self.state is None:
            sigma = self._measurement_sigma(item)
            self.state = np.array([point[0], point[1], 0.0, 0.0, 0.0], dtype=np.float64)
            self.covariance = np.diag([sigma * sigma, sigma * sigma, 100.0, math.pi ** 2, 25.0])
            self.state_time = timestamp
            self.last_detection_time = timestamp
            self.last_bbox = item.bbox
            self.last_confidence = float(np.clip(item.confidence, 0.0, 1.0))
            self.last_anchor = point.copy()
            self.last_aspect = item.aspect
            self._measurement_history = [(timestamp, point.copy())]
            self.accepted_count = 1
            self.last_gate_reasons = ()
            return True

        assert self.covariance is not None and self.state_time is not None
        if timestamp <= self.state_time + 1e-6:
            # Repeated reads of the detector's latest result are normal while
            # the camera advances.  Do not turn that expected condition into a
            # persistent gate reason on the output track.
            return False

        predicted, predicted_covariance = self._predict_pair(
            self.state, self.covariance, timestamp - self.state_time
        )
        sigma = self._measurement_sigma(item)
        measurement_matrix = np.zeros((2, self.STATE_SIZE), dtype=np.float64)
        measurement_matrix[0, 0] = 1.0
        measurement_matrix[1, 1] = 1.0
        innovation = point - predicted[:2]
        innovation_covariance = (
            measurement_matrix @ predicted_covariance @ measurement_matrix.T
            + np.eye(2, dtype=np.float64) * sigma * sigma
        )
        try:
            mahalanobis = float(innovation.T @ np.linalg.solve(innovation_covariance, innovation))
        except np.linalg.LinAlgError:
            mahalanobis = float("inf")

        # Advance the filter clock even for a rejected observation.  This keeps
        # later delayed detections ordered and lets the predicted point continue.
        self.state = predicted
        self.covariance = predicted_covariance
        self.state_time = timestamp
        self.last_gate_reasons = ()
        physical_bound = self.config.max_speed * max(
            timestamp - self.last_detection_time, self.config.min_motion_dt
        ) + 4.0 * sigma
        physical_recovery = (
            math.isfinite(mahalanobis)
            and mahalanobis > self.config.mahalanobis_gate
            and float(np.linalg.norm(innovation)) <= physical_bound
            and timestamp - self.last_detection_time >= 0.08
        )
        if (not math.isfinite(mahalanobis) or mahalanobis > self.config.mahalanobis_gate) and not physical_recovery:
            self.rejected_count += 1
            self.last_gate_reasons = ("MAHALANOBIS_GATE",)
            return False

        if physical_recovery:
            # The axis-aligned box centre can move substantially when a fish
            # rolls.  If the displacement remains physically plausible, snap
            # the position to the new anchor while retaining covariance and
            # use the following observations to re-estimate motion.
            self.state[:2] = point
            self.covariance[0, 0] = max(self.covariance[0, 0], sigma * sigma)
            self.covariance[1, 1] = max(self.covariance[1, 1], sigma * sigma)

        gain = predicted_covariance @ measurement_matrix.T @ np.linalg.inv(innovation_covariance)
        self.state = predicted + gain @ innovation
        if physical_recovery:
            self.state[:2] = point
        self.state[2] = float(np.clip(self.state[2], 0.0, self.config.max_speed))
        self.state[3] = _wrap_angle(self.state[3])
        identity = np.eye(self.STATE_SIZE, dtype=np.float64)
        residual = identity - gain @ measurement_matrix
        measurement_covariance = np.eye(2, dtype=np.float64) * sigma * sigma
        self.covariance = (
            residual @ predicted_covariance @ residual.T
            + gain @ measurement_covariance @ gain.T
        )
        self.covariance = 0.5 * (self.covariance + self.covariance.T)
        try:
            eigenvalues, eigenvectors = np.linalg.eigh(self.covariance)
            self.covariance = (
                eigenvectors
                @ np.diag(np.maximum(eigenvalues, 1e-9))
                @ eigenvectors.T
            )
        except np.linalg.LinAlgError:
            pass
        self._bootstrap_motion(point, timestamp)
        self.last_detection_time = timestamp
        self.last_bbox = item.bbox
        self.last_confidence = float(np.clip(item.confidence, 0.0, 1.0))
        self.last_anchor = point.copy()
        self.last_aspect = item.aspect
        self.accepted_count += 1
        return True

    def _state_at(self, timestamp: float) -> tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        if self.state is None or self.covariance is None or self.state_time is None:
            return None, None
        dt = float(timestamp - self.state_time)
        if dt < -1e-6:
            return self.state.copy(), self.covariance.copy()
        return self._predict_pair(self.state, self.covariance, dt)

    def result(self, timestamp: float) -> FishTrackResult:
        state, covariance = self._state_at(float(timestamp))
        if state is None or covariance is None or self.last_detection_time is None:
            return FishTrackResult(
                class_name=self.class_name,
                track_id=self.track_id,
                source="INVALID",
                position=None,
                predicted_position=None,
                bbox=self.last_bbox,
                confidence=0.0,
                quality=0.0,
                covariance=(float("inf"), float("inf")),
                anchor_ratio=self.anchor_ratio,
                anchor_quality=0.0,
                detection_age_s=None,
                prediction_age_s=None,
                valid=False,
                usable_for_control=False,
                accepted_detection=False,
                gate_reasons=("NO_TRACK",),
            )

        prediction_age = max(0.0, float(timestamp - self.last_detection_time))
        actual_position = np.asarray(state[:2], dtype=np.float64)
        variance = (max(0.0, float(covariance[0, 0])), max(0.0, float(covariance[1, 1])))
        too_uncertain = max(variance) > self.config.covariance_limit
        expired = prediction_age > self.config.max_prediction_s
        valid = not expired and not too_uncertain and np.isfinite(state[:2]).all()
        if valid:
            if (
                self._last_output_position is not None
                and float(np.linalg.norm(actual_position - self._last_output_position))
                < max(0.0, float(self.config.output_deadband))
            ):
                output_position = self._last_output_position.copy()
            else:
                output_position = actual_position.copy()
                self._last_output_position = output_position.copy()
        else:
            output_position = actual_position
        position = (float(output_position[0]), float(output_position[1]))
        predicted_position = (float(actual_position[0]), float(actual_position[1]))
        detected_now = prediction_age <= 1e-5
        source = "DETECTED" if detected_now else "PREDICTED"
        if not valid:
            source = "INVALID"
        confidence_decay = max(0.0, 1.0 - prediction_age / max(self.config.max_prediction_s, 1e-6))
        covariance_quality = 1.0 / (1.0 + math.sqrt(max(variance)) / max(self.config.covariance_limit, 1e-6))
        quality = float(np.clip(self.last_confidence * confidence_decay * covariance_quality, 0.0, 1.0))
        reasons = list(self.last_gate_reasons)
        if expired:
            reasons.append("PREDICTION_TIMEOUT")
        if too_uncertain:
            reasons.append("COVARIANCE_LIMIT")
        accepted = detected_now and not self.last_gate_reasons
        return FishTrackResult(
            class_name=self.class_name,
            track_id=self.track_id,
            source=source,
            position=position if valid else None,
            predicted_position=predicted_position,
            bbox=self.last_bbox,
            confidence=self.last_confidence,
            quality=quality,
            covariance=variance,
            anchor_ratio=self.anchor_ratio,
            anchor_quality=float(np.clip(self.last_confidence * covariance_quality, 0.0, 1.0)),
            detection_age_s=prediction_age,
            prediction_age_s=prediction_age if not detected_now else 0.0,
            valid=valid,
            usable_for_control=valid and prediction_age <= self.config.max_prediction_s,
            accepted_detection=accepted,
            gate_reasons=tuple(dict.fromkeys(reasons)),
        )


class FishTrackManager:
    """Maintain independent class-keyed trackers and persistent anchor ratios."""

    def __init__(
        self,
        *,
        config: Optional[EKFConfig] = None,
        anchors: Optional[Mapping[str, Sequence[float]]] = None,
        class_names: Iterable[str] = ("red_fish", "blue_fish"),
    ):
        configured = anchors or {}
        self.trackers = {
            name: ExtendedKalmanFishTracker(
                name,
                anchor_ratio=configured.get(name, DEFAULT_ANCHOR),
                config=config,
            )
            for name in class_names
        }

    @property
    def anchors(self) -> dict[str, tuple[float, float]]:
        return {name: tracker.anchor_ratio for name, tracker in self.trackers.items()}

    def reset(self) -> None:
        for tracker in self.trackers.values():
            tracker.reset()

    def set_anchor_from_click(
        self,
        class_name: str,
        point: Sequence[float],
        bbox: Sequence[float],
    ) -> tuple[float, float]:
        if class_name not in self.trackers:
            raise KeyError(class_name)
        x1, y1, x2, y2 = [float(v) for v in bbox]
        width, height = x2 - x1, y2 - y1
        if width <= 1e-6 or height <= 1e-6:
            raise ValueError("cannot calibrate an anchor from an empty bbox")
        ratio = (_clip_anchor((float(point[0]) - x1) / width), _clip_anchor((float(point[1]) - y1) / height))
        self.trackers[class_name].set_anchor(*ratio)
        return ratio

    def step(
        self,
        timestamp: float,
        detections: Iterable[FishDetection | Mapping[str, Any]] = (),
    ) -> dict[str, FishTrackResult]:
        parsed = deduplicate_detections(detections)
        for item in parsed:
            if float(item.timestamp) > float(timestamp) + 1e-6:
                # A detector result from a clock domain ahead of the camera
                # frame must not move the filter into the future.
                continue
            tracker = self.trackers.get(item.class_name)
            if tracker is not None:
                tracker.update_detection(item)
        return {name: tracker.result(timestamp) for name, tracker in self.trackers.items()}

    def save_anchors(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "anchors": {
                name: [float(ratio[0]), float(ratio[1])]
                for name, ratio in self.anchors.items()
            },
        }
        destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def load_anchors(path: str | Path) -> dict[str, tuple[float, float]]:
        source = Path(path)
        if not source.is_file():
            return {}
        data = json.loads(source.read_text(encoding="utf-8"))
        raw = data.get("anchors", data)
        result: dict[str, tuple[float, float]] = {}
        for name in ("red_fish", "blue_fish"):
            if name in raw and len(raw[name]) == 2:
                result[name] = (_clip_anchor(raw[name][0]), _clip_anchor(raw[name][1]))
        return result
