#!/usr/bin/env python3
"""Measure YOLO box-size bias against confirmed annotations.

The report is intentionally class-specific: for every image that contains the
requested class, keep only the highest-confidence prediction of that class and
compare it with the confirmed ground-truth box.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--class-id", type=int, default=1)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.05)
    parser.add_argument("--device", default="0")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args()


def iou_xyxy(a: list[float], b: list[float]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] * (hi - pos) + ordered[hi] * (pos - lo)


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    matched = [row for row in rows if row["matched"]]
    result: dict[str, object] = {
        "images": len(rows),
        "matched": len(matched),
        "missed": len(rows) - len(matched),
        "match_rate": len(matched) / len(rows) if rows else None,
    }
    for field in ("confidence", "iou", "width_ratio", "height_ratio", "area_ratio"):
        values = [float(row[field]) for row in matched]
        result[field] = {
            "mean": statistics.fmean(values) if values else None,
            "median": statistics.median(values) if values else None,
            "p10": percentile(values, 0.10),
            "p90": percentile(values, 0.90),
        }
    return result


def main() -> None:
    args = parse_args()
    dataset = args.dataset.resolve()
    annotations = args.annotations.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    gt_by_image: dict[str, dict[str, object]] = {}
    with annotations.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["class_id"]) != args.class_id:
                continue
            image_name = row["image"]
            if image_name in gt_by_image:
                raise ValueError(f"Multiple class {args.class_id} GT boxes in {image_name}")
            gt_by_image[image_name] = {
                "split": row["split"],
                "video_id": row["video_id"],
                "gt": [float(row[key]) for key in ("x1", "y1", "x2", "y2")],
            }

    image_paths = [dataset / "images" / str(meta["video_id"]) / name for name, meta in gt_by_image.items()]
    missing = [str(path) for path in image_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing {len(missing)} images; first: {missing[0]}")

    model = YOLO(str(args.model.resolve()))
    predictions = model.predict(
        source=[str(path) for path in image_paths],
        imgsz=args.imgsz,
        conf=args.conf,
        iou=0.7,
        max_det=20,
        classes=[args.class_id],
        device=args.device,
        stream=True,
        verbose=False,
    )

    rows: list[dict[str, object]] = []
    for result in predictions:
        image_name = Path(result.path).name
        meta = gt_by_image[image_name]
        gt = list(meta["gt"])
        boxes = result.boxes
        row: dict[str, object] = {
            "split": meta["split"],
            "video_id": meta["video_id"],
            "image": image_name,
            "matched": False,
            "confidence": "",
            "iou": "",
            "width_ratio": "",
            "height_ratio": "",
            "area_ratio": "",
            "gt_x1": gt[0],
            "gt_y1": gt[1],
            "gt_x2": gt[2],
            "gt_y2": gt[3],
            "pred_x1": "",
            "pred_y1": "",
            "pred_x2": "",
            "pred_y2": "",
        }
        if boxes is not None and len(boxes):
            best_index = int(boxes.conf.argmax().item())
            pred = boxes.xyxy[best_index].detach().cpu().tolist()
            confidence = float(boxes.conf[best_index].item())
            gt_width, gt_height = gt[2] - gt[0], gt[3] - gt[1]
            pred_width, pred_height = pred[2] - pred[0], pred[3] - pred[1]
            row.update(
                matched=True,
                confidence=confidence,
                iou=iou_xyxy(pred, gt),
                width_ratio=pred_width / gt_width,
                height_ratio=pred_height / gt_height,
                area_ratio=(pred_width * pred_height) / (gt_width * gt_height),
                pred_x1=pred[0],
                pred_y1=pred[1],
                pred_x2=pred[2],
                pred_y2=pred[3],
            )
        rows.append(row)

    fieldnames = list(rows[0]) if rows else []
    with (output_dir / "box_bias.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped["all"].append(row)
        grouped[f"split:{row['split']}"] .append(row)
        grouped[f"video:{row['video_id']}"] .append(row)
        grouped[f"video:{row['video_id']}/split:{row['split']}"] .append(row)
    report = {
        "model": str(args.model.resolve()),
        "dataset": str(dataset),
        "class_id": args.class_id,
        "imgsz": args.imgsz,
        "confidence_floor": args.conf,
        "groups": {name: summarize(group_rows) for name, group_rows in sorted(grouped.items())},
    }
    with (output_dir / "box_bias.json").open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    if not args.quiet:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
