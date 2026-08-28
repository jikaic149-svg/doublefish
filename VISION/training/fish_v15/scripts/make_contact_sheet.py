from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description="Create an evenly sampled contact sheet.")
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples-per-group", type=int, default=6)
    parser.add_argument("--thumb-width", type=int, default=480)
    parser.add_argument("--thumb-height", type=int, default=270)
    parser.add_argument("--columns", type=int, default=6)
    args = parser.parse_args()

    groups = sorted(path for path in args.image_root.iterdir() if path.is_dir())
    direct_files = sorted(args.image_root.glob("*.jpg"))
    if direct_files:
        groups = [args.image_root]
    elif not groups:
        raise FileNotFoundError(f"No JPEG files or image groups under {args.image_root}")

    rows: list[np.ndarray] = []
    for group in groups:
        files = direct_files if group == args.image_root and direct_files else sorted(group.glob("*.jpg"))
        if not files:
            continue
        count = min(args.samples_per_group, len(files))
        indices = np.linspace(0, len(files) - 1, count, dtype=int)
        thumbnails: list[np.ndarray] = []
        for index in indices:
            path = files[int(index)]
            image = cv2.imread(str(path))
            if image is None:
                raise RuntimeError(f"Unable to read {path}")
            scale = min(args.thumb_width / image.shape[1], args.thumb_height / image.shape[0])
            resized_width = max(1, round(image.shape[1] * scale))
            resized_height = max(1, round(image.shape[0] * scale))
            resized = cv2.resize(image, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
            thumb = np.zeros((args.thumb_height, args.thumb_width, 3), dtype=np.uint8)
            offset_x = (args.thumb_width - resized_width) // 2
            offset_y = (args.thumb_height - resized_height) // 2
            thumb[offset_y : offset_y + resized_height, offset_x : offset_x + resized_width] = resized
            cv2.rectangle(thumb, (0, 0), (args.thumb_width, 30), (0, 0, 0), -1)
            cv2.putText(
                thumb,
                f"{group.name}  {path.stem}",
                (8, 21),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
            thumbnails.append(thumb)
        for start in range(0, len(thumbnails), args.columns):
            chunk = thumbnails[start : start + args.columns]
            while len(chunk) < args.columns:
                chunk.append(np.zeros_like(thumbnails[0]))
            rows.append(cv2.hconcat(chunk))

    if not rows:
        raise RuntimeError("No readable images found")
    sheet = cv2.vconcat(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.output), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError(f"Unable to write {args.output}")
    print(f"Contact sheet: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
