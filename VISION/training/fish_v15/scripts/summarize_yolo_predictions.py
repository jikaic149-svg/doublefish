from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


CLASS_NAMES = {0: "red_fish", 1: "blue_fish"}


def read_detections(path: Path) -> list[tuple[int, float]]:
    detections: list[tuple[int, float]] = []
    if not path.exists():
        return detections
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 6:
            raise ValueError(f"Unexpected prediction line in {path}: {line}")
        detections.append((int(parts[0]), float(parts[5])))
    return detections


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize saved YOLO TXT predictions at confidence thresholds.")
    parser.add_argument("--labels-dir", type=Path, required=True)
    parser.add_argument("--image-dir", type=Path, required=True)
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0.1, 0.2, 0.3, 0.4, 0.5])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    image_stems = sorted(path.stem for path in args.image_dir.resolve().glob("*.jpg"))
    labels_dir = args.labels_dir.resolve()
    result: dict[str, object] = {"total_frames": len(image_stems), "thresholds": {}}
    for threshold in args.thresholds:
        frames_with = Counter()
        instances = Counter()
        frames_with_multiple = Counter()
        both = 0
        no_detections = 0
        for stem in image_stems:
            counts = Counter(
                class_id
                for class_id, confidence in read_detections(labels_dir / f"{stem}.txt")
                if confidence >= threshold
            )
            for class_id in CLASS_NAMES:
                if counts[class_id]:
                    frames_with[class_id] += 1
                    instances[class_id] += counts[class_id]
                if counts[class_id] > 1:
                    frames_with_multiple[class_id] += 1
            if counts[0] and counts[1]:
                both += 1
            if not counts[0] and not counts[1]:
                no_detections += 1
        result["thresholds"][f"{threshold:.2f}"] = {
            "frames_with": {CLASS_NAMES[key]: frames_with[key] for key in CLASS_NAMES},
            "instances": {CLASS_NAMES[key]: instances[key] for key in CLASS_NAMES},
            "frames_with_multiple": {CLASS_NAMES[key]: frames_with_multiple[key] for key in CLASS_NAMES},
            "both_classes_frames": both,
            "no_detection_frames": no_detections,
        }

    content = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    print(content, end="")
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
