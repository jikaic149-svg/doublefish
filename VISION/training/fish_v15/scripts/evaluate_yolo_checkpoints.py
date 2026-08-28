#!/usr/bin/env python3
"""Evaluate multiple YOLO checkpoints on identical validation/test splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", action="append", required=True, help="tag=checkpoint.pt")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--device", default="0")
    parser.add_argument("--splits", nargs="+", default=["val", "test"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {"data": str(args.data.resolve()), "imgsz": args.imgsz, "models": {}}
    for specification in args.model:
        tag, separator, raw_path = specification.partition("=")
        if not separator or not tag or not raw_path:
            raise ValueError(f"Invalid --model value: {specification!r}")
        model_path = Path(raw_path).resolve()
        model_report: dict[str, object] = {"path": str(model_path), "splits": {}}
        model = YOLO(str(model_path))
        for split in list(dict.fromkeys(args.splits)):
            metrics = model.val(
                data=str(args.data.resolve()),
                split=split,
                imgsz=args.imgsz,
                batch=4,
                device=args.device,
                workers=0,
                amp=False,
                project=str((args.output / "native").resolve()),
                name=f"{tag}_{split}",
                exist_ok=True,
                plots=True,
                verbose=False,
            )
            per_class: dict[str, object] = {}
            for class_id, class_name in metrics.names.items():
                precision, recall, map50, map50_95 = metrics.box.class_result(class_id)
                per_class[class_name] = {
                    "precision": float(precision),
                    "recall": float(recall),
                    "map50": float(map50),
                    "map50_95": float(map50_95),
                }
            model_report["splits"][split] = {
                "all": {key: float(value) for key, value in metrics.results_dict.items()},
                "classes": per_class,
            }
        report["models"][tag] = model_report

    output_path = args.output / "metrics.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path.resolve())


if __name__ == "__main__":
    main()
