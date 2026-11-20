"""Run the two fixed checkpoints on a frozen, eligible common-class test set."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
from time import perf_counter

import cv2
import numpy as np

from checkpoints import BUNDLED_SHA, HOUDAN_SHA, load_houdan
from dataset import (
    CLASSES, REPO, SPLITS, approved_annotation, benchmark_coverage, digest,
    key, label_text, private_path, read_json, validate_annotation, write_json,
)

NAMES = dict(enumerate(CLASSES))
IOU_LEVELS = np.arange(50, 100, 5) / 100
AP_FLOOR = .001
CONFIDENCE = .25
SETTINGS = {"imgsz": 640, "device": "cpu", "conf": AP_FLOOR, "iou": .7, "max_det": 300,
            "rect": False, "quantize": 32, "verbose": False, "save": False}


def match(targets, predictions, iou_threshold):
    """Match highest-confidence boxes to the best still-unmatched target of the same class."""
    matched = {}
    used = set()
    for p, candidate in sorted(enumerate(predictions), key=lambda item: -item[1][5]):
        x1, y1, x2, y2, label, _ = candidate
        best = iou_threshold
        choice = None
        for t, (a, b, c, d, name) in enumerate(targets):
            if label != name or t in used:
                continue
            intersection = max(0, min(x2, c) - max(x1, a)) * max(0, min(y2, d) - max(y1, b))
            union = (x2 - x1) * (y2 - y1) + (c - a) * (d - b) - intersection
            iou = intersection / union if union > 0 else 0
            if iou >= iou_threshold and (choice is None or iou > best):
                choice, best = t, iou
        if choice is not None:
            matched[p] = choice
            used.add(choice)
    return matched


def frozen_test(root):
    manifest_path = root / "manifest.json"
    manifest = read_json(manifest_path)
    audit = manifest["audit"]
    if manifest["schema"] != 1 or audit["split_blockers"] or audit["benchmark_blockers"]:
        reasons = audit["split_blockers"] + audit["benchmark_blockers"]
        raise ValueError("Benchmark is blocked: " + ("; ".join(reasons) or "unsupported manifest schema"))
    rows = manifest["splits"]["test"]
    _, coverage_blockers = benchmark_coverage(rows)
    if coverage_blockers:
        raise ValueError("Frozen test rows do not meet the benchmark gate: " + "; ".join(coverage_blockers))
    seen_ids, seen_images = set(), set()
    group_split = {}
    for split in SPLITS:
        for row in manifest["splits"][split]:
            i = key(row["id"])
            if i in seen_ids or row["image_sha256"] in seen_images or row["split"] != split:
                raise ValueError(f"Duplicate or misplaced frozen record {i}.")
            seen_ids.add(i)
            seen_images.add(row["image_sha256"])
            if not approved_annotation(row) or row["annotation"]["kind"] == "exclude":
                raise ValueError(f"Frozen annotation is not independently approved for {i}.")
            validate_annotation(row, row["annotation"])
            if split != "train" and row.get("model_assisted"):
                raise ValueError(f"Model-assisted record {i} is outside training.")
            if split == "test" and not row["overlap_evidence"].strip():
                raise ValueError(f"Training independence evidence missing for {i}.")
            for field in ("device", "session"):
                identity = (field, key(row[field]).casefold())
                if group_split.setdefault(identity, split) != split:
                    raise ValueError(f"A frozen {field} occurs across splits.")
            image = root / "images" / split / f"{i}.png"
            label = root / "labels" / split / f"{i}.txt"
            if (digest(image) != row["image_sha256"] or digest(label) != row["label_sha256"]
                    or label.read_text(encoding="utf-8") != label_text(row)):
                raise ValueError(f"Frozen image or label changed for {i}.")

    return rows


def evaluate(root, output, houdan_path, imgsz):
    # Check eligibility and hashes before loading any model.
    data = frozen_test(root)
    settings = {**SETTINGS, "imgsz": imgsz}
    import torch
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.utils.metrics import DetMetrics

    bundled = REPO / "backend/models/revalue_exterior_yolo11n_v0.2.pt"
    if digest(bundled) != BUNDLED_SHA:
        raise ValueError("Bundled checkpoint hash differs from the registered baseline.")
    torch.set_num_threads(2)
    cv2.setNumThreads(2)
    models = {
        "revalue-yolo11n": YOLO(str(bundled)),
        "houdan-yolo11s": load_houdan(houdan_path, YOLO, torch),
    }
    if models["revalue-yolo11n"].names != NAMES:
        raise ValueError("Bundled model's class names are unexpected.")

    output.mkdir(mode=0o700)
    trackers = {name: DetMetrics(NAMES) for name in models}
    counts = {name: {cls: Counter() for cls in CLASSES} for name in models}
    extra = {name: Counter() for name in models}
    timings = {name: [] for name in models}
    rows = []
    first = cv2.imread(str(root / "images/test" / f'{data[0]["id"]}.png'))
    for model in models.values():
        for _ in range(3):
            model.predict(first, **settings)
    for index, row in enumerate(data):
        i = row["id"]
        frame = cv2.imread(str(root / "images/test" / f"{i}.png"))
        if frame is None or frame.shape[:2] != (row["height"], row["width"]):
            raise ValueError(f"Unexpected image dimensions for {i}.")
        targets = [(*b["xyxy"], b["label"]) for b in row["annotation"]["boxes"]]
        classes = np.array([CLASSES.index(box[4]) for box in targets], dtype=int)
        order = tuple(models) if index % 2 == 0 else tuple(reversed(models))
        for name in order:
            start = perf_counter()
            prediction = models[name].predict(frame, **settings)[0]
            timings[name].append((perf_counter() - start) * 1000)
            boxes = []
            for x1, y1, x2, y2, conf, cls in prediction.boxes.data.tolist():
                raw = prediction.names[int(cls)]
                label = "generic_crack" if raw == "crack" else raw
                if label in CLASSES:
                    boxes.append((x1, y1, x2, y2, label, conf))
                elif conf >= CONFIDENCE:
                    extra[name][raw] += 1
            correct = np.zeros((len(boxes), len(IOU_LEVELS)), dtype=bool)
            for j, iou in enumerate(IOU_LEVELS):
                for p in match(targets, boxes, iou):
                    correct[p, j] = True
            trackers[name].update_stats({
                "im_name": i, "tp": correct, "target_cls": classes, "target_img": np.unique(classes),
                "pred_cls": np.array([CLASSES.index(box[4]) for box in boxes], dtype=int),
                "conf": np.array([box[5] for box in boxes]),
            })
            operating_boxes = [box for box in boxes if box[5] >= CONFIDENCE]
            hits = match(targets, operating_boxes, .50)
            for p, box in enumerate(operating_boxes):
                label = box[4]
                counts[name][label]["tp" if p in hits else "fp"] += 1
                if p not in hits:
                    counts[name][label]["fp_clean"] += row["annotation"]["kind"] == "clean"
                    rows.append({"id": i, "model": name, "error": "FP", "label": label, "xyxy": box[:4], "confidence": box[5]})
            claimed = set(hits.values())
            for t, target in enumerate(targets):
                if t not in claimed:
                    counts[name][target[4]]["fn"] += 1
                    rows.append({"id": i, "model": name, "error": "FN", "label": target[4], "xyxy": target[:4]})
    table, summary = [], {}
    for model, tracker in trackers.items():
        tracker.process()
        indices = {cls: i for i, cls in enumerate(tracker.box.ap_class_index)}
        for cls, label in NAMES.items():
            c = counts[model][label]
            tp, fp, fn = c["tp"], c["fp"], c["fn"]
            i = indices.get(cls)
            table.append({
                "model": model, "class": label, "precision": tp / (tp + fp) if tp + fp else 0,
                "recall": tp / (tp + fn), "f1": 2 * tp / (2 * tp + fp + fn),
                "ap50": float(tracker.box.ap50[i]) if i is not None else 0,
                "ap50_95": float(tracker.box.ap[i]) if i is not None else 0,
                "tp": tp, "fp": fp, "fn": fn, "fp_on_clean": c["fp_clean"],
            })
        summary[model] = {
            "mAP50": float(tracker.box.map50), "mAP50_95": float(tracker.box.map),
            "cpu_median_predict_ms": float(np.median(timings[model])),
            "cpu_p95_predict_ms": float(np.percentile(timings[model], 95)),
            "timed_calls": len(timings[model]), "out_of_scope_at_operating_threshold": dict(extra[model]),
        }
    with (output / "per_class.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    write_json(output / "private_errors.json", rows)
    write_json(output / "summary.json", {
        "models": summary, "image_count": len(data), "manifest_sha256": digest(root / "manifest.json"),
        "weights_sha256": {"revalue-yolo11n": BUNDLED_SHA, "houdan-yolo11s": HOUDAN_SHA},
        "settings": settings, "operating_confidence": CONFIDENCE, "match_iou": .50, "cpu_threads": torch.get_num_threads(),
        "torch": torch.__version__, "ultralytics": ultralytics.__version__, "platform": platform.platform(),
        "utc": datetime.now(timezone.utc).isoformat(),
    })


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Frozen dataset export directory")
    parser.add_argument("--imgsz", type=int, choices=(640, 960), default=640)
    parser.add_argument("--houdan", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true", help="Validate frozen data and checkpoint hashes without inference")
    args = parser.parse_args()
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    try:
        dataset = private_path(args.dataset)
        if args.check_only:
            rows = frozen_test(dataset)
            bundled = REPO / "backend/models/revalue_exterior_yolo11n_v0.2.pt"
            if digest(bundled) != BUNDLED_SHA or digest(args.houdan) != HOUDAN_SHA:
                raise ValueError("A checkpoint does not match its pinned SHA-256.")
            print(f"Preflight passed for {len(rows)} test images and both checkpoints. No inference was run.")
        elif args.output:
            evaluate(dataset, private_path(args.output), args.houdan, args.imgsz)
        else:
            parser.error("--output is required for evaluation runs.")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        parser.error(str(exc))
