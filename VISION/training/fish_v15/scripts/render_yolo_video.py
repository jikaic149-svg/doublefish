from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2
from ultralytics import YOLO


CLASS_NAMES = {0: "red_fish", 1: "blue_fish"}
CLASS_COLORS = {0: (32, 32, 235), 1: (235, 180, 20)}


@dataclass(frozen=True)
class Detection:
    class_id: int
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render one highest-confidence YOLO box per class to an MP4 video.")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--confidence", type=float, default=0.20)
    parser.add_argument("--nms-iou", type=float, default=0.70)
    parser.add_argument("--same-class-iou", type=float, default=0.50)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="0")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iou(left: Detection, right: Detection) -> float:
    intersection = max(0.0, min(left.x2, right.x2) - max(left.x1, right.x1)) * max(
        0.0, min(left.y2, right.y2) - max(left.y1, right.y1)
    )
    left_area = max(0.0, left.x2 - left.x1) * max(0.0, left.y2 - left.y1)
    right_area = max(0.0, right.x2 - right.x1) * max(0.0, right.y2 - right.y1)
    union = left_area + right_area - intersection
    return intersection / union if union > 0.0 else 0.0


def select_detections(result: object, same_class_iou: float) -> list[Detection]:
    boxes = result.boxes
    if boxes is None or len(boxes) == 0:
        return []
    coordinates = boxes.xyxy.detach().cpu().tolist()
    confidences = boxes.conf.detach().cpu().tolist()
    classes = boxes.cls.detach().cpu().tolist()
    raw = [
        Detection(int(class_id), float(confidence), *map(float, corners))
        for corners, confidence, class_id in zip(coordinates, confidences, classes)
        if int(class_id) in CLASS_NAMES
    ]
    selected: list[Detection] = []
    for class_id in CLASS_NAMES:
        ordered = sorted(
            (item for item in raw if item.class_id == class_id),
            key=lambda item: item.confidence,
            reverse=True,
        )
        deduplicated: list[Detection] = []
        for detection in ordered:
            if not any(iou(detection, kept) >= same_class_iou for kept in deduplicated):
                deduplicated.append(detection)
        if deduplicated:
            selected.append(deduplicated[0])
    return selected


def draw(frame: object, detections: list[Detection]) -> None:
    height, width = frame.shape[:2]
    thickness = max(2, round(min(width, height) / 360))
    font_scale = max(0.65, min(width, height) / 1200)
    for detection in detections:
        x1 = max(0, min(width - 1, round(detection.x1)))
        y1 = max(0, min(height - 1, round(detection.y1)))
        x2 = max(0, min(width - 1, round(detection.x2)))
        y2 = max(0, min(height - 1, round(detection.y2)))
        color = CLASS_COLORS[detection.class_id]
        label = f"{CLASS_NAMES[detection.class_id]} {detection.confidence:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        text_y = max(text_size[1] + baseline + 8, y1)
        cv2.rectangle(
            frame,
            (x1, text_y - text_size[1] - baseline - 8),
            (min(width - 1, x1 + text_size[0] + 10), text_y + 3),
            color,
            -1,
        )
        cv2.putText(
            frame,
            label,
            (x1 + 5, text_y - baseline - 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (18, 18, 18),
            thickness,
            cv2.LINE_AA,
        )


def main() -> int:
    args = parse_args()
    model_path = args.model.resolve()
    source_path = args.source.resolve()
    output_path = args.output.resolve()
    if args.batch < 1:
        raise ValueError("--batch must be positive")
    if not 0.0 <= args.confidence <= 1.0:
        raise ValueError("--confidence must be between 0 and 1")

    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {source_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if fps <= 0.0 or width <= 0 or height <= 0:
        raise RuntimeError("Invalid source video metadata")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")
    writer = cv2.VideoWriter(
        str(partial_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Unable to create video: {partial_path}")

    model = YOLO(str(model_path))
    processed = 0
    frames_with = Counter()
    instance_counts = Counter()
    start_time = time.perf_counter()
    next_progress = 0
    try:
        while True:
            frames = []
            for _ in range(args.batch):
                ok, frame = capture.read()
                if not ok:
                    break
                frames.append(frame)
            if not frames:
                break
            results = model.predict(
                source=frames,
                imgsz=args.imgsz,
                conf=args.confidence,
                iou=args.nms_iou,
                device=args.device,
                batch=len(frames),
                verbose=False,
            )
            for frame, result in zip(frames, results):
                detections = select_detections(result, args.same_class_iou)
                draw(frame, detections)
                writer.write(frame)
                processed += 1
                present = {item.class_id for item in detections}
                for class_id in present:
                    frames_with[class_id] += 1
                for detection in detections:
                    instance_counts[detection.class_id] += 1

            progress = int(processed * 100 / total_frames) if total_frames else 0
            if progress >= next_progress or processed == total_frames:
                elapsed = time.perf_counter() - start_time
                speed = processed / elapsed if elapsed > 0 else 0.0
                remaining = max(0, total_frames - processed)
                eta = remaining / speed if speed > 0 else 0.0
                print(
                    f"PROGRESS {progress:3d}% frames={processed}/{total_frames} "
                    f"speed={speed:.1f}fps eta={eta:.1f}s",
                    flush=True,
                )
                next_progress = progress + 5
    finally:
        writer.release()
        capture.release()

    if processed != total_frames:
        raise RuntimeError(f"Frame count mismatch: processed {processed}, expected {total_frames}")
    os.replace(partial_path, output_path)
    elapsed = time.perf_counter() - start_time
    summary = {
        "source": str(source_path),
        "output": str(output_path),
        "model": str(model_path),
        "model_sha256": sha256(model_path),
        "settings": {
            "imgsz": args.imgsz,
            "confidence": args.confidence,
            "nms_iou": args.nms_iou,
            "same_class_iou": args.same_class_iou,
            "selection": "same-class deduplicate, then highest-confidence one per class; preserve red/blue overlap",
        },
        "video": {
            "codec": "mp4v",
            "width": width,
            "height": height,
            "fps": fps,
            "frames": processed,
            "duration_seconds": processed / fps,
            "audio": "not copied",
        },
        "frames_with": {CLASS_NAMES[key]: frames_with[key] for key in CLASS_NAMES},
        "rendered_instances": {CLASS_NAMES[key]: instance_counts[key] for key in CLASS_NAMES},
        "processing": {"elapsed_seconds": elapsed, "average_fps": processed / elapsed},
    }
    summary_path = output_path.with_suffix(".json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
