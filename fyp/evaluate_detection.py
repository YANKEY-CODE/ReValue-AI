#!/usr/bin/env python3
"""Compare trusted local YOLO and RT-DETR detection weights on held-out phone images."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL.Image import open as open_image

CLASSES = {0: "generic_crack", 1: "scratch"}
AP_CONF = 0.001
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def class_names(names):
    return dict(enumerate(names)) if isinstance(names, list) else names


def split_images(root, entries):
    entries = [entries] if isinstance(entries, str) else entries
    if not isinstance(entries, list) or not entries:
        raise ValueError("A split must name local image directories or a list of directories.")
    images = []
    for entry in entries:
        if not isinstance(entry, str) or "://" in entry:
            raise ValueError("Dataset entries must be local image directories.")
        folder = (root / entry).resolve()
        if not folder.is_dir():
            raise ValueError(f"Image directory not found: {folder}")
        images.extend(path for path in folder.rglob("*") if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file())
    if not images:
        raise ValueError("Split contains no supported images.")
    return sorted(images)


def label_counts(label):
    counts = [0, 0]
    if not label.is_file():
        raise ValueError(f"Missing box annotation: {label}. Use an empty file for a reviewed negative.")
    rows = set()
    for line in label.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            cls, x, y, width, height = map(float, line.split())
            if cls not in CLASSES or not all(math.isfinite(v) for v in (x, y, width, height)):
                raise ValueError
            if not (0 < width <= 1 and 0 < height <= 1 and 0 <= x <= 1 and 0 <= y <= 1):
                raise ValueError
            row = (cls, x, y, width, height)
            if row in rows:
                raise ValueError
        except ValueError as exc:
            raise ValueError(f"Invalid or duplicate normalized detection box in {label}: {line}") from exc
        rows.add(row)
        counts[int(cls)] += 1
    return counts


def audit_dataset(config, data_path):
    from ultralytics.data.utils import img2label_paths

    if not isinstance(config, dict) or class_names(config.get("names")) != CLASSES:
        raise ValueError(f"Dataset names must use the class IDs {CLASSES}.")
    root = (data_path.parent / config.get("path", ".")).resolve()
    images = split_images(root, config.get("test"))
    held_out = set()
    labels_seen = set()
    counts = [0, 0]
    negatives = 0
    fingerprint = []
    pairs = []
    for image, label in zip(images, map(Path, img2label_paths([str(p) for p in images])), strict=True):
        if "images" not in image.parts or label.resolve() in labels_seen:
            raise ValueError(f"Expected a unique YOLO images/labels pair for {image}.")
        labels_seen.add(label.resolve())
        with open_image(image) as source:
            if min(source.size) < 10:
                raise ValueError(f"Image is too small for validation: {image}")
            source.verify()
        if image.suffix.lower() in {".jpg", ".jpeg"}:
            with image.open("rb") as stream:
                stream.seek(-2, 2)
                if stream.read() != b"\xff\xd9":
                    raise ValueError(f"Incomplete JPEG: {image}")
        digest = sha256(image)
        if digest in held_out:
            raise ValueError(f"Duplicate test image: {image}")
        held_out.add(digest)
        row_counts = label_counts(label)
        counts = [a + b for a, b in zip(counts, row_counts, strict=True)]
        negatives += not any(row_counts)
        fingerprint.append([digest, sha256(label)])
        pairs.append((image, label))
    if not all(counts):
        raise ValueError("The test split needs ground truth for both crack and scratch.")
    for name in ("train", "val"):
        if config.get(name):
            for image in split_images(root, config[name]):
                if sha256(image) in held_out:
                    raise ValueError(f"Test image also occurs in {name}: {image}")
    return pairs, counts, negatives, hashlib.sha256(json.dumps(sorted(fingerprint)).encode()).hexdigest()


def scores(tp, predicted, targets):
    precision = tp / predicted if predicted else 0.0
    recall = tp / targets
    return {
        "precision": precision, "recall": recall,
        "f1": 2 * tp / (predicted + targets),
        "tp": tp, "fp": predicted - tp, "fn": targets - tp, "targets": targets,
    }


def operating_validator(base, threshold, totals):
    """Count class-aware matches at IoU .50 without changing the AP pass."""
    class OperatingValidator(base):
        def update_metrics(self, preds, batch):
            super().update_metrics(preds, batch)
            for index, prediction in enumerate(preds):
                keep = prediction["conf"] >= threshold
                pred = self._prepare_pred({key: value[keep] for key, value in prediction.items()})
                targets = self._prepare_batch(index, batch)
                matched = self._process_batch(pred, targets)["tp"][:, 0]
                classes = pred["cls"].cpu().numpy()
                for cls in CLASSES:
                    totals[cls][0] += int(matched[classes == cls].sum())
                    count = int((classes == cls).sum())
                    totals[cls][1] += count
                    if not len(targets["cls"]):
                        totals[cls][2] += count

    return OperatingValidator


def save_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="Local YOLO dataset YAML")
    parser.add_argument("--models", nargs="+", required=True, help="One or more trusted local .pt checkpoints")
    parser.add_argument("--family", nargs="+", choices=("yolo", "rtdetr"), help="One family per checkpoint (default: all yolo)")
    parser.add_argument("--output", type=Path, required=True, help="New directory for one run")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--dataset-version", required=True, help="Version of the labelled test data")
    args = parser.parse_args()
    paths = [Path(model).resolve() for model in args.models]
    families = args.family or ["yolo"] * len(paths)
    if len(families) != len(paths) or len(set(paths)) != len(paths):
        parser.error("Specify one family per distinct model.")
    if any(path.suffix.lower() != ".pt" or not path.is_file() for path in paths):
        parser.error("Every model must be an existing local .pt checkpoint.")
    if args.output.exists() or args.batch < 1 or args.imgsz < 32 or args.imgsz % 32:
        parser.error("Use a new output directory, positive batch, and image size divisible by 32.")
    if not AP_CONF <= args.confidence <= 1:
        parser.error("Confidence must be between 0.001 and 1.")
    if not args.data.is_file():
        parser.error(f"Dataset YAML not found: {args.data}")
    import torch
    import ultralytics
    import yaml
    from ultralytics import RTDETR, YOLO
    from ultralytics.models.rtdetr.val import RTDETRValidator
    from ultralytics.models.yolo.detect.val import DetectionValidator

    try:
        config = yaml.safe_load(args.data.read_text(encoding="utf-8"))
        pairs, targets, negatives, fingerprint = audit_dataset(config, args.data.resolve())
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))

    args.output.mkdir(parents=True)
    summaries, per_class, model_metadata = [], [], []
    with TemporaryDirectory(prefix="revalue-eval-") as directory:
        # Isolate Ultralytics caches from the original dataset and keep filenames unique.
        scratch = Path(directory)
        staged_images, staged_labels = scratch / "images", scratch / "labels"
        staged_images.mkdir()
        staged_labels.mkdir()
        for index, (image, label) in enumerate(pairs):
            for source, destination in (
                (image, staged_images / f"{index}{image.suffix.lower()}"),
                (label, staged_labels / f"{index}.txt"),
            ):
                try:
                    destination.symlink_to(source)
                except OSError:
                    shutil.copyfile(source, destination)
        data = scratch / "data.yaml"
        data.write_text(yaml.safe_dump({"names": CLASSES, "train": None, "val": None, "test": str(staged_images)}), encoding="utf-8")
        for index, (path, family) in enumerate(zip(paths, families, strict=True), 1):
            model_id = f"{index:02d}-{path.stem}"
            builder, validator = (YOLO, DetectionValidator) if family == "yolo" else (RTDETR, RTDETRValidator)
            model = builder(str(path))
            if model.task != "detect" or class_names(model.names) != CLASSES:
                parser.error(f"{path.name}: expected detection weights with class IDs {CLASSES}.")
            totals = [[0, 0, 0] for _ in CLASSES]
            metrics = model.val(
                validator=operating_validator(validator, args.confidence, totals),
                data=str(data), split="test", imgsz=args.imgsz, batch=args.batch, device=args.device,
                conf=AP_CONF, rect=False, iou=0.7, max_det=300, workers=0, quantize=32, augment=False,
                plots=False, project=str(args.output.resolve() / "runs"), name=model_id,
            )
            if list(metrics.nt_per_class) != targets:
                raise RuntimeError("Validation target counts differ from the audited labels.")
            ap_indices = {int(cls): i for i, cls in enumerate(metrics.box.ap_class_index)}
            latency = {f"{stage}_ms_per_image": float(metrics.speed[stage]) for stage in ("preprocess", "inference", "postprocess")}
            for cls, name in CLASSES.items():
                i = ap_indices.get(cls)
                per_class.append({
                    "model": model_id, "class_id": cls, "class_name": name,
                    **scores(*totals[cls][:2], targets[cls]),
                    "fp_on_negative_images": totals[cls][2],
                    "ap50": float(metrics.box.ap50[i]) if i is not None else 0.0,
                    "ap50_95": float(metrics.box.ap[i]) if i is not None else 0.0,
                })
            summaries.append({
                "model": model_id, "family": family, "test_images": len(pairs), "negative_images": negatives,
                **scores(sum(row[0] for row in totals), sum(row[1] for row in totals), sum(targets)),
                "fp_on_negative_images": sum(row[2] for row in totals),
                "mAP50": float(metrics.box.map50), "mAP50_95": float(metrics.box.map), **latency,
            })
            model_metadata.append({"model": model_id, "filename": path.name, "family": family, "sha256": sha256(path)})
    save_csv(args.output / "summary.csv", summaries)
    save_csv(args.output / "per_class.csv", per_class)
    manifest = {
        "utc_timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset_version": args.dataset_version, "dataset_yaml_sha256": sha256(args.data),
        "test_content_sha256": fingerprint, "split": "test", "models": model_metadata,
        "requested_image_size": args.imgsz, "batch": args.batch, "device": args.device,
        "confidence": args.confidence, "matching_iou": 0.50, "ap_conf_floor": AP_CONF,
        "nms_iou_where_applicable": 0.7, "max_detections": 300, "precision": "float32",
        "platform": platform.platform(), "python": platform.python_version(),
        "ultralytics": ultralytics.__version__, "torch": torch.__version__,
        "cpu_threads": torch.get_num_threads(),
        "note": "Summary P/R/F1 are micro-averaged at the fixed operating point. AP uses ranked detections.",
    }
    (args.output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Evaluation outputs saved in {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
