from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cv2


CLASS_NAMES = {0: "red_fish", 1: "blue_fish"}
CLASS_COLORS = {0: (255, 40, 20), 1: (220, 220, 0)}


@dataclass(frozen=True)
class Detection:
    class_id: int
    center_x: float
    center_y: float
    width: float
    height: float
    confidence: float

    def corners(self) -> tuple[float, float, float, float]:
        return (
            self.center_x - self.width / 2.0,
            self.center_y - self.height / 2.0,
            self.center_x + self.width / 2.0,
            self.center_y + self.height / 2.0,
        )

    def yolo_line(self) -> str:
        return (
            f"{self.class_id} {self.center_x:.8f} {self.center_y:.8f} "
            f"{self.width:.8f} {self.height:.8f} {self.confidence:.6f}"
        )


def read_detections(path: Path) -> list[Detection]:
    if not path.exists():
        return []
    detections: list[Detection] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 6:
            raise ValueError(f"Unexpected prediction line in {path}: {line}")
        detections.append(
            Detection(
                class_id=int(parts[0]),
                center_x=float(parts[1]),
                center_y=float(parts[2]),
                width=float(parts[3]),
                height=float(parts[4]),
                confidence=float(parts[5]),
            )
        )
    return detections


def intersection_over_union(left: Detection, right: Detection) -> float:
    lx1, ly1, lx2, ly2 = left.corners()
    rx1, ry1, rx2, ry2 = right.corners()
    intersection_width = max(0.0, min(lx2, rx2) - max(lx1, rx1))
    intersection_height = max(0.0, min(ly2, ry2) - max(ly1, ry1))
    intersection = intersection_width * intersection_height
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union if union > 0.0 else 0.0


def filter_class(
    detections: list[Detection],
    overlap_iou: float,
    max_per_class: int,
) -> tuple[list[Detection], int, int]:
    ordered = sorted(detections, key=lambda item: item.confidence, reverse=True)
    deduplicated: list[Detection] = []
    overlap_suppressed = 0
    for detection in ordered:
        if any(intersection_over_union(detection, kept) >= overlap_iou for kept in deduplicated):
            overlap_suppressed += 1
            continue
        deduplicated.append(detection)
    extra_discarded = max(0, len(deduplicated) - max_per_class)
    return deduplicated[:max_per_class], overlap_suppressed, extra_discarded


def render(image_path: Path, detections: list[Detection], output_path: Path) -> None:
    image = cv2.imread(str(image_path))
    if image is None:
        raise RuntimeError(f"Unable to decode {image_path}")
    height, width = image.shape[:2]
    for detection in detections:
        x1, y1, x2, y2 = detection.corners()
        pixel_box = (
            max(0, min(width - 1, round(x1 * width))),
            max(0, min(height - 1, round(y1 * height))),
            max(0, min(width - 1, round(x2 * width))),
            max(0, min(height - 1, round(y2 * height))),
        )
        color = CLASS_COLORS[detection.class_id]
        cv2.rectangle(image, pixel_box[:2], pixel_box[2:], color, 4)
        label = f"{CLASS_NAMES[detection.class_id]} {detection.confidence:.2f}"
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        text_x = pixel_box[0]
        text_y = max(text_size[1] + baseline + 4, pixel_box[1])
        cv2.rectangle(
            image,
            (text_x, text_y - text_size[1] - baseline - 4),
            (text_x + text_size[0] + 6, text_y + 2),
            color,
            -1,
        )
        cv2.putText(
            image,
            label,
            (text_x + 3, text_y - baseline),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (20, 20, 20),
            2,
            cv2.LINE_AA,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image, [cv2.IMWRITE_JPEG_QUALITY, 94]):
        raise RuntimeError(f"Unable to write {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Keep the highest-confidence YOLO box per class and suppress overlaps.")
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--labels-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-confidence", type=float, default=0.25)
    parser.add_argument("--overlap-iou", type=float, default=0.50)
    parser.add_argument("--max-per-class", type=int, default=1)
    args = parser.parse_args()
    if not 0.0 <= args.min_confidence <= 1.0:
        raise ValueError("--min-confidence must be between 0 and 1")
    if not 0.0 <= args.overlap_iou <= 1.0:
        raise ValueError("--overlap-iou must be between 0 and 1")
    if args.max_per_class < 1:
        raise ValueError("--max-per-class must be positive")

    image_dir = args.image_dir.resolve()
    labels_dir = args.labels_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_labels = output_dir / "labels"
    output_labels.mkdir(parents=True, exist_ok=True)

    raw_instances = Counter()
    kept_instances = Counter()
    frames_with = Counter()
    overlap_suppressed = Counter()
    extra_discarded = Counter()
    image_paths = sorted(image_dir.glob("*.jpg"))
    for image_path in image_paths:
        raw = [
            item
            for item in read_detections(labels_dir / f"{image_path.stem}.txt")
            if item.confidence >= args.min_confidence
        ]
        kept: list[Detection] = []
        for class_id in CLASS_NAMES:
            class_detections = [item for item in raw if item.class_id == class_id]
            raw_instances[class_id] += len(class_detections)
            selected, overlap_count, extra_count = filter_class(
                class_detections,
                args.overlap_iou,
                args.max_per_class,
            )
            kept.extend(selected)
            kept_instances[class_id] += len(selected)
            frames_with[class_id] += bool(selected)
            overlap_suppressed[class_id] += overlap_count
            extra_discarded[class_id] += extra_count

        kept.sort(key=lambda item: item.class_id)
        label_content = "\n".join(item.yolo_line() for item in kept)
        (output_labels / f"{image_path.stem}.txt").write_text(
            label_content + ("\n" if label_content else ""),
            encoding="utf-8",
        )
        render(image_path, kept, output_dir / image_path.name)

    summary = {
        "total_frames": len(image_paths),
        "min_confidence": args.min_confidence,
        "overlap_iou": args.overlap_iou,
        "max_per_class": args.max_per_class,
        "rule": "same-class overlaps are one target; keep the highest-confidence box, then keep at most max_per_class",
        "raw_instances": {CLASS_NAMES[key]: raw_instances[key] for key in CLASS_NAMES},
        "kept_instances": {CLASS_NAMES[key]: kept_instances[key] for key in CLASS_NAMES},
        "frames_with": {CLASS_NAMES[key]: frames_with[key] for key in CLASS_NAMES},
        "overlap_suppressed": {CLASS_NAMES[key]: overlap_suppressed[key] for key in CLASS_NAMES},
        "nonoverlap_extras_discarded": {CLASS_NAMES[key]: extra_discarded[key] for key in CLASS_NAMES},
    }
    content = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    (output_dir / "filter_summary.json").write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
