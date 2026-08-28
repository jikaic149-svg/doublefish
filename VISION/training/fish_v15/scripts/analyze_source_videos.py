#!/usr/bin/env python3
"""Read source videos directly and summarize actual visual degradations."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np


def metrics(frame: np.ndarray) -> dict[str, float]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    edges = cv2.Canny(gray, 80, 180)
    glare = (value >= 245) & (saturation <= 70)
    broad_reflection = (value >= 225) & (saturation <= 95)
    means = frame.reshape(-1, 3).mean(axis=0)
    return {
        "brightness_mean": float(gray.mean()),
        "brightness_std": float(gray.std()),
        "saturation_mean": float(saturation.mean()),
        "dark_ratio": float(np.mean(gray <= 35)),
        "bright_ratio": float(np.mean(gray >= 235)),
        "glare_ratio": float(np.mean(glare)),
        "reflection_ratio": float(np.mean(broad_reflection)),
        "edge_ratio": float(np.mean(edges > 0)),
        "laplacian_variance": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
        "blue_mean": float(means[0]),
        "green_mean": float(means[1]),
        "red_mean": float(means[2]),
    }


def percentile_summary(rows: list[dict[str, object]], field: str) -> dict[str, float]:
    values = np.array([float(row[field]) for row in rows], dtype=np.float64)
    return {
        "min": float(values.min()),
        "p05": float(np.percentile(values, 5)),
        "median": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "max": float(values.max()),
    }


def fit_panel(frame: np.ndarray, title: str, details: str) -> np.ndarray:
    panel = cv2.resize(frame, (400, 225), interpolation=cv2.INTER_AREA)
    cv2.rectangle(panel, (0, 0), (400, 43), (0, 0, 0), -1)
    cv2.putText(panel, title, (6, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(panel, details, (6, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (220, 220, 220), 1, cv2.LINE_AA)
    return panel


def write_sheet(panels: list[np.ndarray], output: Path, columns: int = 4) -> None:
    while panels and len(panels) % columns:
        panels.append(np.zeros_like(panels[0]))
    sheet = cv2.vconcat([cv2.hconcat(panels[index:index + columns]) for index in range(0, len(panels), columns)])
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise RuntimeError(f"Unable to write {output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument("--uniform-per-video", type=int, default=20)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with args.manifest.resolve().open("r", encoding="utf-8-sig", newline="") as handle:
        sources = list(csv.DictReader(handle))
    all_rows: list[dict[str, object]] = []
    thumbnails: dict[tuple[str, int], np.ndarray] = {}

    for source in sources:
        video_id = source["video_id"]
        path = Path(source["source_path"])
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            raise RuntimeError(f"Unable to open {path}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        sample_interval = max(1, round(fps * args.sample_seconds))
        frame_index = 0
        pending_gray: np.ndarray | None = None
        pending_row: dict[str, object] | None = None
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if pending_gray is not None and pending_row is not None:
                current_gray = cv2.cvtColor(cv2.resize(frame, (480, 270), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
                difference = cv2.absdiff(pending_gray, current_gray)
                pending_row["next_frame_diff_mean"] = float(difference.mean())
                pending_row["next_frame_diff_p95"] = float(np.percentile(difference, 95))
                pending_gray = None
                pending_row = None
            if frame_index % sample_interval == 0:
                row: dict[str, object] = {
                    "video_id": video_id,
                    "source_file": path.name,
                    "frame_index": frame_index,
                    "timestamp_ms": round(frame_index / fps * 1000),
                    **metrics(frame),
                    "next_frame_diff_mean": 0.0,
                    "next_frame_diff_p95": 0.0,
                }
                all_rows.append(row)
                thumbnails[(video_id, frame_index)] = frame.copy()
                pending_gray = cv2.cvtColor(cv2.resize(frame, (480, 270), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
                pending_row = row
            frame_index += 1
        capture.release()

    with (output / "frame_metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(all_rows[0]))
        writer.writeheader()
        writer.writerows(all_rows)

    fields = [
        "brightness_mean", "brightness_std", "saturation_mean", "dark_ratio", "bright_ratio",
        "glare_ratio", "reflection_ratio", "edge_ratio", "laplacian_variance",
        "blue_mean", "green_mean", "red_mean", "next_frame_diff_mean", "next_frame_diff_p95",
    ]
    summary: dict[str, object] = {}
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in all_rows:
        grouped[str(row["video_id"])].append(row)
    for video_id, rows in grouped.items():
        summary[video_id] = {
            "sampled_frames": len(rows),
            "metrics": {field: percentile_summary(rows, field) for field in fields},
        }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    uniform_panels: list[np.ndarray] = []
    for video_id, rows in grouped.items():
        indices = np.linspace(0, len(rows) - 1, min(args.uniform_per_video, len(rows)), dtype=int)
        for index in indices:
            row = rows[int(index)]
            frame = thumbnails[(video_id, int(row["frame_index"]))]
            uniform_panels.append(
                fit_panel(
                    frame,
                    f"{video_id} {float(row['timestamp_ms']) / 1000:.1f}s",
                    f"Y={float(row['brightness_mean']):.0f} glare={float(row['glare_ratio']):.3f} blur={float(row['laplacian_variance']):.0f}",
                )
            )
    write_sheet(uniform_panels, output / "uniform_contact_sheet.jpg")

    extremes: list[tuple[str, bool]] = [
        ("brightness_mean", False),
        ("brightness_mean", True),
        ("glare_ratio", True),
        ("reflection_ratio", True),
        ("laplacian_variance", False),
        ("edge_ratio", True),
        ("next_frame_diff_mean", True),
    ]
    extreme_panels: list[np.ndarray] = []
    used: set[tuple[str, int]] = set()
    for video_id, rows in grouped.items():
        for field, descending in extremes:
            ordered = sorted(rows, key=lambda row: float(row[field]), reverse=descending)
            row = next((item for item in ordered if (video_id, int(item["frame_index"])) not in used), ordered[0])
            key = (video_id, int(row["frame_index"]))
            used.add(key)
            frame = thumbnails[key]
            direction = "high" if descending else "low"
            extreme_panels.append(
                fit_panel(
                    frame,
                    f"{video_id} {float(row['timestamp_ms']) / 1000:.1f}s {direction} {field}",
                    f"value={float(row[field]):.4f}",
                )
            )
    write_sheet(extreme_panels, output / "extremes_contact_sheet.jpg")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
