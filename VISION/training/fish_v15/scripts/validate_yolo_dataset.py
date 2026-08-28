#!/usr/bin/env python3
"""Validate YOLO image/label pairing, coordinates, splits and exact duplicates."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

import cv2


def label_path(image_path: Path) -> Path:
    parts = list(image_path.parts)
    index = parts.index("images")
    parts[index] = "labels"
    return Path(*parts).with_suffix(".txt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "val", "test"],
        help="Split files to validate from dataset/splits (default: train val test)",
    )
    args = parser.parse_args()
    dataset = args.dataset.resolve()

    split_paths: dict[str, list[Path]] = {}
    errors: list[str] = []
    instances: Counter[int] = Counter()
    images_by_video: Counter[str] = Counter()
    empty_labels = 0
    hashes: dict[str, list[tuple[str, str]]] = defaultdict(list)
    timestamps: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    split_names = list(dict.fromkeys(args.splits))
    for split in split_names:
        split_file = dataset / "splits" / f"{split}.txt"
        if not split_file.is_file():
            errors.append(f"missing split file: {split_file}")
            split_paths[split] = []
            continue
        entries = split_file.read_text(encoding="utf-8").splitlines()
        split_paths[split] = [(dataset / "splits" / entry).resolve() for entry in entries if entry.strip()]
        for image_path in split_paths[split]:
            if not image_path.is_file():
                errors.append(f"missing image: {image_path}")
                continue
            image = cv2.imread(str(image_path))
            if image is None:
                errors.append(f"undecodable image: {image_path}")
                continue
            current_label = label_path(image_path)
            if not current_label.is_file():
                errors.append(f"missing label: {current_label}")
                continue
            lines = current_label.read_text(encoding="utf-8").splitlines()
            if not lines:
                empty_labels += 1
            for line_number, line in enumerate(lines, start=1):
                parts = line.split()
                if len(parts) != 5:
                    errors.append(f"invalid fields: {current_label}:{line_number}")
                    continue
                try:
                    class_id = int(parts[0])
                    x, y, width, height = map(float, parts[1:])
                except ValueError:
                    errors.append(f"non-numeric label: {current_label}:{line_number}")
                    continue
                if class_id not in {0, 1}:
                    errors.append(f"invalid class: {current_label}:{line_number}")
                if not (0 < width <= 1 and 0 < height <= 1 and 0 <= x <= 1 and 0 <= y <= 1):
                    errors.append(f"invalid normalized box: {current_label}:{line_number}")
                if x - width / 2 < -1e-6 or y - height / 2 < -1e-6 or x + width / 2 > 1 + 1e-6 or y + height / 2 > 1 + 1e-6:
                    errors.append(f"box outside image: {current_label}:{line_number}")
                instances[class_id] += 1
            video_id = image_path.parent.name
            images_by_video[video_id] += 1
            try:
                timestamp = int(image_path.name.split("__t", 1)[1].split("ms", 1)[0])
                timestamps[video_id][split].append(timestamp)
            except (IndexError, ValueError):
                pass
            digest = hashlib.sha1(image_path.read_bytes()).hexdigest()
            hashes[digest].append((split, str(image_path)))

    overlaps: dict[str, int] = {}
    for left, right in itertools.combinations(split_names, 2):
        count = len(set(split_paths[left]) & set(split_paths[right]))
        overlaps[f"{left}_{right}"] = count
        if count:
            errors.append(f"split path overlap {left}/{right}: {count}")
    cross_split_duplicates = []
    for digest, members in hashes.items():
        member_splits = {item[0] for item in members}
        if len(member_splits) > 1:
            cross_split_duplicates.append({"sha1": digest, "members": members})
    if cross_split_duplicates:
        errors.append(f"exact duplicate images across splits: {len(cross_split_duplicates)}")

    minimum_time_gap: dict[str, dict[str, int | None]] = {}
    for video_id, split_times in timestamps.items():
        minimum_time_gap[video_id] = {}
        for right in (name for name in split_names if name != "train"):
            left = "train"
            if split_times[left] and split_times[right]:
                gap = min(abs(a - b) for a in split_times[left] for b in split_times[right])
            else:
                gap = None
            minimum_time_gap[video_id][f"{left}_{right}_ms"] = gap

    report = {
        "dataset": str(dataset),
        "images": {split: len(paths) for split, paths in split_paths.items()},
        "total_images": sum(len(paths) for paths in split_paths.values()),
        "images_by_video": dict(images_by_video),
        "instances": {str(key): value for key, value in sorted(instances.items())},
        "empty_labels": empty_labels,
        "split_path_overlaps": overlaps,
        "exact_cross_split_duplicates": len(cross_split_duplicates),
        "minimum_time_gap": minimum_time_gap,
        "errors": errors,
        "valid": not errors,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
