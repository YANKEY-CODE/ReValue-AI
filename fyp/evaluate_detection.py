#!/usr/bin/env python3
"""Evaluate YOLO detection models on a single held-out test split.

Requires: pip install ultralytics pyyaml
Usage:
python fyp/evaluate_detection.py --data /path/to/data.yaml --models backend/models/revalue_exterior_yolo11n_v0.2.pt --device cpu
The YAML must declare 'test:'; this script does not train or download data.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_class_rows(metrics: Any, model_name: str) -> list[dict[str, Any]]:
    box = metrics.box
    class_ids = list(getattr(box, "ap_class_index", []))
    names = getattr(metrics, "names", {})
    out = []
    for i, cls in enumerate(class_ids):
        class_id = int(cls)
        label = names.get(class_id, str(class_id)) if isinstance(names, dict) else names[class_id]
        out.append({
            "model": model_name, "class_id": class_id, "class_name": label,
            "precision": float(box.p[i]), "recall": float(box.r[i]),
            "mAP50": float(box.ap50[i]), "mAP50_95": float(box.ap[i]),
        })
    return out


def save_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="YOLO dataset YAML with a test: split")
    parser.add_argument("--models", nargs="+", type=Path, required=True, help="Detection .pt weights")
    parser.add_argument("--output", type=Path, default=Path("fyp/results"))
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    if not args.data.is_file():
        parser.error(f"Dataset YAML not found: {args.data}")
    missing = [str(model) for model in args.models if not model.is_file()]
    if missing:
        parser.error("Model file(s) missing: " + ", ".join(missing))
    try:
        import yaml
        from ultralytics import YOLO
    except ImportError as exc:
        parser.error("Install dependencies: pip install ultralytics pyyaml (" + str(exc) + ")")
    with args.data.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict) or not config.get("test"):
        parser.error("Dataset YAML must contain a non-empty 'test:' split independent of training data")

    args.output.mkdir(parents=True, exist_ok=True)
    summaries = []
    per_class = []
    for i, path in enumerate(args.models, 1):
        model = YOLO(str(path))
        if getattr(model, "task", None) != "detect":
            raise ValueError(f"{path}: model task {model.task!r} is not detection; segmentation requires a separate protocol")
        metrics = model.val(
            data=str(args.data.resolve()), split="test", imgsz=args.imgsz,
            batch=args.batch, device=args.device, conf=0.001,
            project=str((args.output / "runs").resolve()),
            name=f"model_{i}_{path.stem}", exist_ok=True, plots=True, verbose=False,
        )
        summaries.append({
            "model": path.name,
            "precision": float(metrics.box.mp), "recall": float(metrics.box.mr),
            "mAP50": float(metrics.box.map50), "mAP50_95": float(metrics.box.map),
            "inference_ms_per_image": float(metrics.speed.get("inference", -1)),
        })
        per_class.extend(get_class_rows(metrics, path.name))
    save_csv(args.output / "summary.csv", summaries,
             ["model", "precision", "recall", "mAP50", "mAP50_95", "inference_ms_per_image"])
    save_csv(args.output / "per_class.csv", per_class,
             ["model", "class_id", "class_name", "precision", "recall", "mAP50", "mAP50_95"])
    manifest = {
        "utc_timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_yaml": str(args.data.resolve()),
        "models": [str(m.resolve()) for m in args.models],
        "test_split": config["test"],
        "image_size": args.imgsz, "batch": args.batch, "device": args.device,
        "note": "Compare only on the same held-out split. Check near-duplicate leakage and dataset permissions.",
    }
    (args.output / "run_manifest.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"Evaluation outputs saved in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
