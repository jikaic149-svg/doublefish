from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


EXPECTED_CLASSES = {"v01": {0}, "v02": {0, 1}, "v03": {1}}
NAMES = {0: "red_fish", 1: "blue_fish"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a temporal large-review package.")
    parser.add_argument("--review-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.review_root.resolve()
    with (root / "review_queue.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    errors: list[str] = []
    images: set[str] = set()
    queue_indices: set[int] = set()
    class_counts: Counter[int] = Counter()
    empty_labels = 0
    for row in rows:
        image_name = row["image"]
        queue_index = int(row["queue_index"])
        if image_name in images:
            errors.append(f"duplicate image: {image_name}")
        if queue_index in queue_indices:
            errors.append(f"duplicate queue index: {queue_index}")
        images.add(image_name)
        queue_indices.add(queue_index)
        batch = root / "batches" / row["review_batch"]
        image_path = batch / "images" / image_name
        yolo_path = batch / "labels_yolo" / f"{Path(image_name).stem}.txt"
        xlabel_path = batch / "labels_xlabel" / f"{Path(image_name).stem}.json"
        for path in (image_path, yolo_path, xlabel_path):
            if not path.is_file():
                errors.append(f"missing: {path}")
        if not yolo_path.is_file() or not xlabel_path.is_file():
            continue

        classes: list[int] = []
        for line_number, line in enumerate(yolo_path.read_text(encoding="utf-8").splitlines(), start=1):
            fields = line.split()
            if len(fields) != 5:
                errors.append(f"{yolo_path}:{line_number} expected 5 fields")
                continue
            try:
                class_id = int(fields[0])
                coords = [float(value) for value in fields[1:]]
            except ValueError:
                errors.append(f"{yolo_path}:{line_number} invalid number")
                continue
            if class_id not in {0, 1}:
                errors.append(f"{yolo_path}:{line_number} class {class_id}")
            if not all(0.0 <= value <= 1.0 for value in coords) or coords[2] <= 0 or coords[3] <= 0:
                errors.append(f"{yolo_path}:{line_number} invalid coordinates")
            classes.append(class_id)
            class_counts[class_id] += 1
        if not classes:
            empty_labels += 1
        if len(classes) != len(set(classes)):
            errors.append(f"duplicate class in {yolo_path}")
        if not set(classes) <= EXPECTED_CLASSES[row["video_id"]]:
            errors.append(f"scene class policy violation in {yolo_path}: {classes}")

        try:
            xlabel = json.loads(xlabel_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as error:
            errors.append(f"invalid JSON {xlabel_path}: {error}")
            continue
        if xlabel.get("imagePath") != image_name:
            errors.append(f"imagePath mismatch: {xlabel_path}")
        shapes = xlabel.get("shapes", [])
        if len(shapes) != len(classes):
            errors.append(f"JSON/YOLO shape mismatch: {image_name}")
        json_labels = [shape.get("label") for shape in shapes]
        expected_labels = [NAMES[class_id] for class_id in classes]
        if json_labels != expected_labels:
            errors.append(f"JSON/YOLO class mismatch: {image_name}")
        for shape in shapes:
            if shape.get("shape_type") != "rectangle" or len(shape.get("points", [])) != 4:
                errors.append(f"invalid rectangle: {xlabel_path}")

    report = {
        "review_root": str(root),
        "queue_images": len(rows),
        "unique_images": len(images),
        "queue_index_contiguous": queue_indices == set(range(1, len(rows) + 1)),
        "class_instances": {NAMES[class_id]: class_counts[class_id] for class_id in sorted(NAMES)},
        "empty_labels": empty_labels,
        "roles": dict(Counter(row["split_role"] for row in rows)),
        "methods": dict(Counter(row["candidate_method"] for row in rows)),
        "pending_status_rows": sum(
            1
            for path in (root / "batches").glob("*/review_status.csv")
            for status in list(csv.DictReader(path.open("r", encoding="utf-8-sig", newline="")))
            if status["status"] == "pending"
        ),
        "errors": errors,
        "valid": not errors and queue_indices == set(range(1, len(rows) + 1)),
    }
    (root / "validation_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
