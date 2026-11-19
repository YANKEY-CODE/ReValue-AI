"""Create optional bundled-detector proposals for private training images only."""

import argparse
import json
import math
import os
from pathlib import Path

import cv2

from dataset import (
    CLASSES, REPO, digest, duplicate_candidates, key, practice_ids, private_path, read_json, records, write_json,
)
from evaluate import BUNDLED_SHA, CONFIDENCE, SETTINGS


def training_record(root, identifier):
    path = root / "records" / f"{key(identifier)}.json"
    row = read_json(path)
    if row["split"] != "train" or identifier in practice_ids(root) or not all(row[k] for k in ("device", "session")):
        raise ValueError("Proposals require a non-practice training image with known device and session.")
    return path, row


def proposal_plan(root, identifiers=None):
    rows = records(root)
    reserved = practice_ids(root)
    protected = [r for r in rows.values() if r["id"] in reserved or r["split"] in ("val", "test")]
    known = {field: {r[field].casefold() for r in protected if r[field]} for field in ("device", "session")}
    selected = (list(dict.fromkeys(identifiers)) if identifiers is not None
                else [i for i, r in rows.items() if r["split"] == "train"])
    reviews_path = root / "duplicate_reviews.json"
    reviews = read_json(reviews_path) if reviews_path.is_file() else {}
    plan = {"eligible_ids": [], "blocked": {}, "pool_count": sum(r["split"] == "pool" for r in rows.values())}
    for ident in selected:
        try:
            _, row = training_record(root, ident)
        except (ValueError, OSError) as exc:
            plan["blocked"][ident] = str(exc)
            continue
        fields = [f for f in ("device", "session") if row[f].casefold() in known[f]]
        if fields:
            plan["blocked"][ident] = "Shares " + "/".join(fields) + " with practice, validation or test."
            continue
        for other in protected:
            for a, b, kind in duplicate_candidates((row, other)):
                pair = ":".join(sorted((a, b)))
                rationale = reviews.get(pair)
                if kind == "exact" or not isinstance(rationale, str) or not rationale.strip():
                    plan["blocked"][ident] = f"Unresolved {kind} duplicate of protected image {other['id']}."
            if ident in plan["blocked"]:
                break
        if ident not in plan["blocked"]:
            plan["eligible_ids"].append(ident)
    return plan


def propose(root, identifiers):
    # Check the whole request for leakage before loading a detector.
    plan = proposal_plan(root, identifiers)
    if plan["blocked"]:
        blocked = "; ".join(f"{i}: {reason}" for i, reason in plan["blocked"].items())
        if identifiers is not None:
            raise ValueError(blocked)
        print("Skipping blocked training records: " + blocked)
    if not plan["eligible_ids"]:
        print("No eligible training images. No detector was loaded.")
        return
    batch = [training_record(root, identifier) for identifier in plan["eligible_ids"]]
    weights = REPO / "backend/models/revalue_exterior_yolo11n_v0.2.pt"
    if digest(weights) != BUNDLED_SHA:
        raise ValueError("Bundled checkpoint hash differs from the registered baseline.")
    from ultralytics import YOLO

    model = YOLO(str(weights))
    output = root / "proposals"
    output.mkdir(mode=0o700, exist_ok=True)
    for path, row in batch:
        i = row["id"]
        image = root / "images" / f"{i}.png"
        if digest(image) != row["image_sha256"]:
            raise ValueError(f"Image changed for {i}.")
        frame = cv2.imread(str(image))
        if frame is None:
            raise ValueError(f"Cannot decode image {i}.")
        prediction = model.predict(frame, **{**SETTINGS, "conf": CONFIDENCE, "max_det": 40})[0]
        boxes = []
        for x1, y1, x2, y2, confidence, cls in prediction.boxes.data.tolist():
            label = prediction.names[int(cls)]
            coords = [math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2)]
            if label in CLASSES and 0 <= coords[0] < coords[2] <= row["width"] and 0 <= coords[1] < coords[3] <= row["height"]:
                boxes.append({"label": label, "xyxy": coords, "confidence": round(confidence, 4)})
        # Keep proposals separate from human labels; the marker survives deletion of a sidecar.
        write_json(path, {**row, "model_assisted": True})
        write_json(output / path.name, {"id": i, "image_sha256": row["image_sha256"], "weights_sha256": BUNDLED_SHA,
                                       "imgsz": SETTINGS["imgsz"], "confidence": CONFIDENCE, "authority": "ai_proposal_only", "boxes": boxes})
    print(f"Wrote {len(batch)} training proposal file(s). Human annotations and reviews were not edited.")


def proposal_for(root, identifier):
    _, row = training_record(root, identifier)
    blocked = proposal_plan(root, [identifier])["blocked"]
    if blocked:
        raise ValueError(blocked[identifier])
    sidecar = read_json(root / "proposals" / f"{identifier}.json")
    if (not row.get("model_assisted") or sidecar["id"] != identifier
            or sidecar["image_sha256"] != row["image_sha256"] or sidecar["weights_sha256"] != BUNDLED_SHA):
        raise ValueError("Proposal does not match the registered training photo and checkpoint.")
    return sidecar["boxes"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("ids", nargs="*")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="List eligible training images and blockers; do not run inference")
    mode.add_argument("--all-training", action="store_true", help="Propose for the current training split")
    args = parser.parse_args()
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    try:
        root = private_path(args.root)
        if args.plan:
            print(json.dumps(proposal_plan(root, args.ids or None), indent=2))
        elif args.all_training and not args.ids:
            propose(root, None)
        elif args.ids and not args.all_training:
            propose(root, args.ids)
        else:
            parser.error("Choose --plan, --all-training or explicit image IDs.")
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
