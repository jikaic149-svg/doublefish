#!/usr/bin/env python3
"""Build V15 from a trusted base plus all approved temporal-review batches."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
from collections import Counter
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--review-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--isolation-ms", type=int, default=5000)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"Refusing to write an empty manifest: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def copy_or_link(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        try:
            os.link(source, destination)
            return "hardlink"
        except OSError:
            pass
    shutil.copy2(source, destination)
    return "copy"


def copy_tree(source: Path, destination: Path) -> Counter[str]:
    modes: Counter[str] = Counter()
    for path in source.rglob("*"):
        if path.is_file() and path.suffix.lower() != ".cache":
            modes[copy_or_link(path, destination / path.relative_to(source))] += 1
    return modes


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def split_entries(dataset: Path, split: str) -> list[str]:
    path = dataset / "splits" / f"{split}.txt"
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_label(path: Path) -> Counter[int]:
    instances: Counter[int] = Counter()
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"Approved training label is empty: {path}")
    for line_number, line in enumerate(lines, start=1):
        fields = line.split()
        if len(fields) != 5:
            raise ValueError(f"Invalid field count: {path}:{line_number}")
        class_id = int(fields[0])
        coordinates = list(map(float, fields[1:]))
        if class_id not in {0, 1}:
            raise ValueError(f"Invalid class ID: {path}:{line_number}")
        x, y, width, height = coordinates
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
            raise ValueError(f"Invalid normalized box: {path}:{line_number}")
        if x - width / 2 < -1e-6 or y - height / 2 < -1e-6:
            raise ValueError(f"Box outside image: {path}:{line_number}")
        if x + width / 2 > 1 + 1e-6 or y + height / 2 > 1 + 1e-6:
            raise ValueError(f"Box outside image: {path}:{line_number}")
        instances[class_id] += 1
    return instances


def image_name_from_entry(entry: str) -> str:
    return Path(entry.replace("\\", "/")).name


def video_and_timestamp(entry: str) -> tuple[str, int]:
    image_name = image_name_from_entry(entry)
    video_id = image_name.split("__", 1)[0]
    timestamp_ms = int(Path(image_name).stem.split("__t", 1)[1].removesuffix("ms"))
    return video_id, timestamp_ms


def main() -> int:
    args = parse_args()
    base = args.base.resolve()
    review_root = args.review_root.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")

    batch_roots = sorted((review_root / "batches").glob("train_candidate_*"))
    if len(batch_roots) != 8:
        raise ValueError(f"Expected 8 train-candidate batches, found {len(batch_roots)}")

    base_splits = {name: split_entries(base, name) for name in ("train", "val", "test", "tight_test")}
    protected_names = {
        image_name_from_entry(entry)
        for split in ("val", "test", "tight_test")
        for entry in base_splits[split]
    }
    protected_times: dict[str, list[int]] = {}
    for split in ("val", "test", "tight_test"):
        for entry in base_splits[split]:
            video_id, timestamp_ms = video_and_timestamp(entry)
            protected_times.setdefault(video_id, []).append(timestamp_ms)

    original_base_train = list(base_splits["train"])
    removed_base_train: list[str] = []
    kept_base_train: list[str] = []
    for entry in original_base_train:
        video_id, timestamp_ms = video_and_timestamp(entry)
        if any(
            abs(timestamp_ms - held_timestamp) < args.isolation_ms
            for held_timestamp in protected_times.get(video_id, [])
        ):
            removed_base_train.append(entry)
        else:
            kept_base_train.append(entry)
    base_splits["train"] = kept_base_train

    modes = copy_tree(base, output)
    train_entries = list(base_splits["train"])
    train_entry_set = set(train_entries)
    base_train_names = {image_name_from_entry(entry) for entry in train_entries}
    seen_images: set[str] = set()
    manifest_rows: list[dict[str, object]] = []
    instances: Counter[int] = Counter()
    methods: Counter[str] = Counter()
    videos: Counter[str] = Counter()
    changed_images = 0
    overridden_images = 0
    added_images = 0

    for batch_root in batch_roots:
        manifest = {row["image"]: row for row in read_csv(batch_root / "batch_manifest.csv")}
        statuses = read_csv(batch_root / "review_status.csv")
        changes_path = review_root / "reports" / batch_root.name / "human_review_changes.csv"
        changes = {row["image"]: row for row in read_csv(changes_path)}
        if len(statuses) != len(manifest):
            raise ValueError(f"Manifest/status mismatch in {batch_root.name}")

        for status in statuses:
            image_name = status["image"]
            if status["status"] != "approved":
                raise ValueError(f"Unapproved image in training batch: {batch_root.name}/{image_name}")
            if image_name in seen_images:
                raise ValueError(f"Duplicate reviewed image across batches: {image_name}")
            if image_name in protected_names:
                raise ValueError(f"Reviewed training image overlaps a protected split: {image_name}")
            _, reviewed_timestamp = video_and_timestamp(image_name)
            if any(
                abs(reviewed_timestamp - held_timestamp) < args.isolation_ms
                for held_timestamp in protected_times.get(status["video_id"], [])
            ):
                raise ValueError(f"Reviewed image violates the isolation window: {image_name}")
            seen_images.add(image_name)

            row = manifest[image_name]
            video_id = row["video_id"]
            source_image = batch_root / "images" / image_name
            source_label = batch_root / "labels_reviewed_yolo" / f"{Path(image_name).stem}.txt"
            if not source_image.is_file() or not source_label.is_file():
                raise FileNotFoundError(f"Missing reviewed pair: {batch_root.name}/{image_name}")
            instances.update(parse_label(source_label))

            destination_image = output / "images" / video_id / image_name
            destination_label = output / "labels" / video_id / f"{Path(image_name).stem}.txt"
            existed = image_name in base_train_names
            if existed:
                if not destination_image.is_file() or not destination_label.is_file():
                    raise FileNotFoundError(f"Base train pair is incomplete: {image_name}")
                if file_digest(source_image) != file_digest(destination_image):
                    raise ValueError(f"Same-name base/review images differ: {image_name}")
                shutil.copy2(source_label, destination_label)
                modes["label_override"] += 1
                overridden_images += 1
            else:
                if destination_image.exists() or destination_label.exists():
                    raise FileExistsError(f"Unexpected destination collision: {image_name}")
                modes[copy_or_link(source_image, destination_image)] += 1
                modes[copy_or_link(source_label, destination_label)] += 1
                entry = f"./../images/{video_id}/{image_name}"
                if entry in train_entry_set:
                    raise ValueError(f"Duplicate train entry: {entry}")
                train_entries.append(entry)
                train_entry_set.add(entry)
                added_images += 1

            change = changes.get(image_name)
            changed = bool(change and change.get("changed", "").lower() == "true")
            changed_images += int(changed)
            methods[row["candidate_method"]] += 1
            videos[video_id] += 1
            manifest_rows.append(
                {
                    "batch": batch_root.name,
                    "queue_index": row["queue_index"],
                    "video_id": video_id,
                    "image": image_name,
                    "timestamp_ms": row["timestamp_ms"],
                    "candidate_method": row["candidate_method"],
                    "human_changed": changed,
                    "dataset_action": "override" if existed else "add",
                    "annotation_source": "human_reviewed_v15",
                    "status": "approved",
                }
            )

    expected = json.loads((review_root / "summary.json").read_text(encoding="utf-8"))["roles"]["train_candidate"]
    if len(seen_images) != expected:
        raise ValueError(f"Expected {expected} reviewed train candidates, found {len(seen_images)}")
    if overridden_images + added_images != expected:
        raise AssertionError("Reviewed image accounting mismatch")

    (output / "splits" / "train.txt").write_text(
        "\n".join(train_entries) + "\n", encoding="utf-8", newline="\n"
    )
    write_csv(output / "v15_reviewed_manifest.csv", manifest_rows)
    summary = {
        "base_dataset": str(base),
        "review_root": str(review_root),
        "base_train_images": len(original_base_train),
        "base_train_removed_for_isolation": len(removed_base_train),
        "base_train_kept": len(base_splits["train"]),
        "isolation_ms": args.isolation_ms,
        "reviewed_train_candidates": len(seen_images),
        "reviewed_overrides": overridden_images,
        "reviewed_additions": added_images,
        "human_changed_images": changed_images,
        "final_train_images": len(train_entries),
        "preserved_splits": {
            "val": len(base_splits["val"]),
            "test": len(base_splits["test"]),
            "tight_test": len(base_splits["tight_test"]),
        },
        "reviewed_instances": {"red_fish": instances[0], "blue_fish": instances[1]},
        "reviewed_videos": dict(sorted(videos.items())),
        "reviewed_candidate_methods": dict(sorted(methods.items())),
        "pseudo_labels_added": 0,
        "image_materialization": dict(modes),
        "policy": (
            "trusted V13 base with all 498 explicitly user-reviewed train candidates; "
            "reviewed labels override same-name base labels; val/test/tight_test unchanged"
        ),
    }
    (output / "v15_reviewed_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
