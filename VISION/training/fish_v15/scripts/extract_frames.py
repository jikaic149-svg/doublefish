from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract timestamped JPEG frames from MP4 videos.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--project-dir", type=Path, required=True)
    parser.add_argument("--interval-sec", type=float, default=1.0)
    parser.add_argument("--jpeg-quality", type=int, default=92)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def codec_name(value: int) -> str:
    return "".join(chr((value >> (8 * index)) & 0xFF) for index in range(4))


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    if args.interval_sec <= 0:
        raise ValueError("--interval-sec must be greater than zero")
    if not 1 <= args.jpeg_quality <= 100:
        raise ValueError("--jpeg-quality must be between 1 and 100")

    input_dir = args.input_dir.resolve()
    project_dir = args.project_dir.resolve()
    image_root = project_dir / "review" / "pending" / "images"
    frame_manifest_path = project_dir / "review" / "pending" / "frames.csv"
    source_manifest_path = project_dir / "sources" / "manifest.csv"
    videos = sorted(input_dir.glob("*.mp4"))

    if not videos:
        raise FileNotFoundError(f"No MP4 videos found under {input_dir}")
    if not args.overwrite and any(image_root.rglob("*.jpg")):
        raise FileExistsError(f"JPEG frames already exist under {image_root}; use --overwrite to replace them")

    image_root.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, object]] = []
    frame_rows: list[dict[str, object]] = []
    total_saved = 0

    for video_number, video_path in enumerate(videos, start=1):
        video_id = f"v{video_number:02d}"
        output_dir = image_root / video_id
        output_dir.mkdir(parents=True, exist_ok=True)

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open video: {video_path}")

        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        codec = codec_name(int(capture.get(cv2.CAP_PROP_FOURCC)))
        if not math.isfinite(fps) or fps <= 0 or frame_count <= 0:
            capture.release()
            raise RuntimeError(f"Invalid video metadata: {video_path}")

        duration_sec = frame_count / fps
        sample_count = math.ceil(duration_sec / args.interval_sec)
        target_frames = [
            min(round(sample_number * args.interval_sec * fps), frame_count - 1)
            for sample_number in range(sample_count)
        ]
        target_frames = list(dict.fromkeys(target_frames))
        target_index = 0
        source_frame = 0
        saved_for_video = 0

        print(
            f"[{video_id}] {video_path.name}: {width}x{height}, {fps:.3f} FPS, "
            f"{duration_sec:.3f} s, targets={len(target_frames)}",
            flush=True,
        )

        while target_index < len(target_frames):
            ok, frame = capture.read()
            if not ok:
                capture.release()
                raise RuntimeError(
                    f"Decode stopped at frame {source_frame}/{frame_count} for {video_path.name}"
                )

            if source_frame >= target_frames[target_index]:
                timestamp_ms = round(source_frame * 1000.0 / fps)
                image_name = (
                    f"{video_id}__f{source_frame:09d}__t{timestamp_ms:09d}ms.jpg"
                )
                image_path = output_dir / image_name
                if image_path.exists() and not args.overwrite:
                    capture.release()
                    raise FileExistsError(f"Refusing to overwrite {image_path}")
                saved = cv2.imwrite(
                    str(image_path),
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, args.jpeg_quality],
                )
                if not saved:
                    capture.release()
                    raise RuntimeError(f"Failed to write {image_path}")

                frame_rows.append(
                    {
                        "video_id": video_id,
                        "source_file": video_path.name,
                        "relative_image": image_path.relative_to(project_dir).as_posix(),
                        "source_frame": source_frame,
                        "timestamp_ms": timestamp_ms,
                        "width": width,
                        "height": height,
                    }
                )
                target_index += 1
                saved_for_video += 1
                total_saved += 1
                if saved_for_video % 100 == 0:
                    print(f"[{video_id}] saved {saved_for_video}/{len(target_frames)}", flush=True)

            source_frame += 1

        capture.release()
        source_rows.append(
            {
                "video_id": video_id,
                "source_file": video_path.name,
                "source_path": str(video_path.resolve()),
                "bytes": video_path.stat().st_size,
                "codec": codec,
                "fps": f"{fps:.9f}",
                "frames": frame_count,
                "duration_sec": f"{duration_sec:.6f}",
                "width": width,
                "height": height,
                "sampling_interval_sec": f"{args.interval_sec:.6f}",
                "extracted_frames": saved_for_video,
            }
        )
        print(f"[{video_id}] complete: {saved_for_video} frames", flush=True)

    write_csv(
        source_manifest_path,
        [
            "video_id",
            "source_file",
            "source_path",
            "bytes",
            "codec",
            "fps",
            "frames",
            "duration_sec",
            "width",
            "height",
            "sampling_interval_sec",
            "extracted_frames",
        ],
        source_rows,
    )
    write_csv(
        frame_manifest_path,
        [
            "video_id",
            "source_file",
            "relative_image",
            "source_frame",
            "timestamp_ms",
            "width",
            "height",
        ],
        frame_rows,
    )
    print(f"Extraction complete: videos={len(videos)}, frames={total_saved}", flush=True)
    print(f"Source manifest: {source_manifest_path}", flush=True)
    print(f"Frame manifest: {frame_manifest_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
