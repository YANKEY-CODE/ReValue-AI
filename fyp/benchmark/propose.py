"""Create optional bundled-detector proposals for private training images only."""

import argparse
import math
import os
from pathlib import Path

import cv2

from dataset import CLASSES, REPO, digest, key, practice_ids, private_path, read_json, write_json
from evaluate import BUNDLED_SHA, CONFIDENCE, SETTINGS


def training_record(root, identifier):
    path = root / "records" / f"{key(identifier)}.json"
    row = read_json(path)
    if row["split"] != "train" or identifier in practice_ids(root) or not all(row[k] for k in ("device", "session")):
        raise ValueError("Proposals require a non-practice training image with known device and session.")
    return path, row


def propose(root, identifiers):
    # Validate all requested images before loading a detector.
    batch = [training_record(root, identifier) for identifier in dict.fromkeys(identifiers)]
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
                                       "imgsz": SETTINGS["imgsz"], "confidence": CONFIDENCE, "boxes": boxes})
    print(f"Wrote {len(batch)} training proposal file(s). Human annotations and reviews were not edited.")


def proposal_for(root, identifier):
    _, row = training_record(root, identifier)
    sidecar = read_json(root / "proposals" / f"{identifier}.json")
    if (not row.get("model_assisted") or sidecar["id"] != identifier
            or sidecar["image_sha256"] != row["image_sha256"] or sidecar["weights_sha256"] != BUNDLED_SHA):
        raise ValueError("Proposal does not match the registered training photo and checkpoint.")
    return sidecar["boxes"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("ids", nargs="+")
    args = parser.parse_args()
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    try:
        propose(private_path(args.root), args.ids)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
