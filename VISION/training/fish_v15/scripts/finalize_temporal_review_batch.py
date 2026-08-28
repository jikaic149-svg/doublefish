from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


LABEL_TO_ID = {"red_fish": 0, "blue_fish": 1}
SCENE_CLASSES = {"v01": {0}, "v02": {0, 1}, "v03": {1}}


@dataclass(frozen=True)
class Box:
    class_id: int
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def xyxy(self) -> tuple[float, float, float, float]:
        return self.x - self.w / 2, self.y - self.h / 2, self.x + self.w / 2, self.y + self.h / 2

    def yolo_line(self) -> str:
        return f"{self.class_id} {self.x:.8f} {self.y:.8f} {self.w:.8f} {self.h:.8f}"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def validate_box(box: Box, path: Path) -> None:
    values = (box.x, box.y, box.w, box.h)
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"Non-finite box in {path}")
    x1, y1, x2, y2 = box.xyxy
    if box.w <= 0 or box.h <= 0 or x1 < 0 or y1 < 0 or x2 > 1 or y2 > 1:
        raise ValueError(f"Out-of-bounds box in {path}: {box}")


def read_yolo(path: Path) -> dict[int, Box]:
    boxes: dict[int, Box] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"Invalid YOLO row in {path}: {line!r}")
        box = Box(int(fields[0]), *map(float, fields[1:]))
        if box.class_id in boxes:
            raise ValueError(f"Duplicate class {box.class_id} in {path}")
        validate_box(box, path)
        boxes[box.class_id] = box
    return boxes


def read_xlabel(path: Path) -> dict[int, Box]:
    data = json.loads(path.read_text(encoding="utf-8"))
    width, height = int(data["imageWidth"]), int(data["imageHeight"])
    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid image dimensions in {path}")
    boxes: dict[int, Box] = {}
    for shape in data.get("shapes", []):
        label = shape.get("label")
        if label not in LABEL_TO_ID or shape.get("shape_type") != "rectangle":
            raise ValueError(f"Invalid label or shape in {path}: {label}")
        points = shape.get("points", [])
        if len(points) < 2:
            raise ValueError(f"Too few rectangle points in {path}")
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
        class_id = LABEL_TO_ID[label]
        if class_id in boxes:
            raise ValueError(f"Duplicate class {class_id} in {path}")
        box = Box(
            class_id,
            ((x1 + x2) / 2) / width,
            ((y1 + y2) / 2) / height,
            (x2 - x1) / width,
            (y2 - y1) / height,
        )
        validate_box(box, path)
        boxes[class_id] = box
    return boxes


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a.xyxy
    bx1, by1, bx2, by2 = b.xyxy
    overlap = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a.area + b.area - overlap
    return overlap / union if union > 0 else 0.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize one human-reviewed temporal batch.")
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    args = parser.parse_args()
    batch = args.batch.resolve()
    report_root = args.report_root.resolve()
    report_root.mkdir(parents=True, exist_ok=True)

    manifest_rows = read_csv(batch / "batch_manifest.csv")
    status_rows = read_csv(batch / "review_status.csv")
    if not manifest_rows or len(manifest_rows) != len(status_rows):
        raise ValueError("Manifest/status count mismatch")

    reviewed: dict[str, dict[int, Box]] = {}
    comparisons: list[dict[str, object]] = []
    instances: Counter[int] = Counter()
    changed_images = 0
    for row in manifest_rows:
        image_name = row["image"]
        stem = Path(image_name).stem
        before = read_yolo(batch / "labels_yolo" / f"{stem}.txt")
        after = read_xlabel(batch / "labels_xlabel" / f"{stem}.json")
        video_id = row["video_id"]
        expected = SCENE_CLASSES[video_id]
        if set(after) != expected:
            raise ValueError(f"{image_name}: expected classes {expected}, got {set(after)}")
        reviewed[image_name] = after
        instances.update(after.keys())
        class_ious = {class_id: iou(before[class_id], after[class_id]) for class_id in after if class_id in before}
        minimum_iou = min(class_ious.values()) if class_ious else 0.0
        changed = set(before) != set(after) or minimum_iou < 0.9995
        changed_images += int(changed)
        comparisons.append(
            {
                "image": image_name,
                "video_id": video_id,
                "timestamp_ms": row["timestamp_ms"],
                "candidate_method": row["candidate_method"],
                "changed": changed,
                "minimum_iou": minimum_iou,
                "red_iou": class_ious.get(0, ""),
                "blue_iou": class_ious.get(1, ""),
                "red_area_ratio": after[0].area / before[0].area if 0 in after and 0 in before else "",
                "blue_area_ratio": after[1].area / before[1].area if 1 in after and 1 in before else "",
            }
        )

    output_root = batch / "labels_reviewed_yolo"
    output_root.mkdir(parents=True, exist_ok=True)
    for image_name, boxes in reviewed.items():
        text = "\n".join(boxes[class_id].yolo_line() for class_id in sorted(boxes)) + "\n"
        (output_root / f"{Path(image_name).stem}.txt").write_text(text, encoding="utf-8", newline="\n")

    for row in status_rows:
        row["status"] = "approved"
        row["reason"] = "human_review_confirmed"
        row["notes"] = "saved by user; converted from X-AnyLabeling and mechanically validated"
    write_csv(batch / "review_status.csv", status_rows)
    write_csv(report_root / "human_review_changes.csv", comparisons)
    report = {
        "valid": True,
        "batch": batch.name,
        "reviewed_images": len(reviewed),
        "approved_images": len(status_rows),
        "changed_images": changed_images,
        "instances": {"red_fish": instances[0], "blue_fish": instances[1]},
        "invalid_boxes": 0,
        "class_policy_errors": 0,
        "promotion_ready": True,
    }
    (report_root / "human_review_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
