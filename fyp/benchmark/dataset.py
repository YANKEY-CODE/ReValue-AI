"""Manage a private, human-reviewed smartphone detection dataset."""

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path
from tempfile import TemporaryDirectory
import re
import shutil
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image, ImageOps

CLASSES = ("generic_crack", "scratch")
SPLITS = ("train", "val", "test")
PROVENANCE = ("device", "session", "split", "overlap_evidence")
OPTIONAL_PROVENANCE = ("capture_date", "permission_ref")
REPO = Path(__file__).resolve().parents[2]
BI_URL = "https://github.com/MHCI/broken-interfaces/tree/37877e61c93e17975a8a5968baefad3dba0b3231"
BI_ATTRIBUTION = "Schaub et al., Broken Display = Broken Interface?, CHI 2014, doi:10.1145/2556288.2557067"


def private_path(path):
    path = Path(path).resolve()
    if path.is_relative_to(REPO) or REPO.is_relative_to(path):
        raise ValueError("Use a dedicated private directory outside the repository.")
    return path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, data):
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def records(root):
    return {p.stem: read_json(p) for p in sorted((root / "records").glob("*.json"))}


def key(text):
    if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", text):
        raise ValueError("Use an identifier of up to 64 letters, numbers, dots, underscores or dashes.")
    return text


def register(root, image_path, source, asset, license_terms, attribution, view):
    if not all(isinstance(item, str) and item.strip() for item in (source, asset, license_terms, attribution)):
        raise ValueError("A source, source asset ID, reuse terms and attribution are required.")
    for folder in ("records", "images"):
        (root / folder).mkdir(mode=0o700, parents=True, exist_ok=True)
    image_id = hashlib.sha256(f"{source}\0{asset}".encode()).hexdigest()[:20]
    image_sha = digest(image_path)
    record_path = root / "records" / f"{image_id}.json"
    if record_path.exists():
        if read_json(record_path)["original_sha256"] != image_sha:
            raise ValueError("Source asset bytes changed; register a new version.")
        return image_id
    with Image.open(image_path) as raw:
        if raw.width * raw.height > 24_000_000 or getattr(raw, "n_frames", 1) != 1:
            raise ValueError("Use a still image of at most 24 megapixels.")
        image = ImageOps.exif_transpose(raw).convert("RGB")
    if min(image.size) < 10:
        raise ValueError("Image is too small.")
    fingerprint = image_signature(image)
    path = root / "images" / f"{image_id}.png"
    # Use the same upright, metadata-free pixels for labeling and inference.
    image.save(path, format="PNG", compress_level=1)
    write_json(record_path, {
        "id": image_id, "source": source, "source_asset": asset, "license_terms": license_terms,
        "attribution": attribution, "original_sha256": image_sha, "image_sha256": digest(path),
        "width": image.width, "height": image.height, "signature": fingerprint,
        "view": view, "device": "", "session": "", "overlap_evidence": "", "split": "pool",
        "annotation": None, "review": None,
    })
    return image_id


def image_signature(image):
    gray = image.convert("L")
    small = np.asarray(gray.resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float32)
    dct = cv2.dct(small)[:8, :8].flatten()[1:]
    dx = np.asarray(gray.resize((9, 8), Image.Resampling.LANCZOS))
    return {
        "pixel_sha256": hashlib.sha256(f"{image.width}x{image.height}:".encode() + image.tobytes()).hexdigest(),
        "phash": int.from_bytes(np.packbits(dct > np.median(dct)).tobytes(), "big"),
        "dhash": int.from_bytes(np.packbits(dx[:, 1:] > dx[:, :-1]).tobytes(), "big"),
    }


def validate_annotation(record, payload):
    kind = payload.get("kind")
    actor = key(payload.get("actor"))
    note = payload.get("note")
    boxes = payload.get("boxes")
    if not isinstance(note, str) or not note.strip() or len(note) > 2000:
        raise ValueError("Add a note about coverage, damage or the reason for exclusion.")
    if kind not in ("positive", "clean", "exclude") or not isinstance(boxes, list):
        raise ValueError("Choose positive, clean or exclude.")
    if bool(boxes) != (kind == "positive") or len(boxes) > 200:
        raise ValueError("Positives require boxes. Clean and excluded images must have none.")
    seen, clean_boxes = set(), []
    for box in boxes:
        if not isinstance(box, dict) or box.get("label") not in CLASSES:
            raise ValueError("Invalid benchmark class.")
        coords = box.get("xyxy")
        if not isinstance(coords, list) or len(coords) != 4 or any(type(v) is not int for v in coords):
            raise ValueError("Use integer pixel corners [x1,y1,x2,y2].")
        x1, y1, x2, y2 = coords
        if not (0 <= x1 < x2 <= record["width"] and 0 <= y1 < y2 <= record["height"]):
            raise ValueError("Box must have positive area and fit inside the image.")
        signature = (box["label"], *coords)
        if signature in seen:
            raise ValueError("Identical boxes are not allowed.")
        seen.add(signature)
        clean_boxes.append({"label": box["label"], "xyxy": coords})
    return {"kind": kind, "actor": actor, "note": note.strip(), "boxes": clean_boxes}


def annotation_digest(annotation):
    return hashlib.sha256(json.dumps(annotation, sort_keys=True).encode()).hexdigest()


def approved_annotation(record):
    annotation, review = record["annotation"], record["review"]
    return bool(annotation and review and review["decision"] == "approved"
                and review.get("annotation_sha256") == annotation_digest(annotation)
                and annotation["actor"].casefold() != review["actor"].casefold())


def update_record(record, action, payload):
    if action == "annotate":
        record["annotation"] = validate_annotation(record, payload)
        record["review"] = None
    elif action == "review":
        annotation = record["annotation"]
        if not annotation:
            raise ValueError("Submit an annotation before reviewing.")
        actor = key(payload.get("actor"))
        if actor.casefold() == annotation["actor"].casefold():
            raise ValueError("An independent reviewer must use their own ID.")
        note, decision = payload.get("note"), payload.get("decision")
        if not isinstance(note, str) or not note.strip() or len(note) > 2000 or decision not in ("approved", "revise"):
            raise ValueError("Choose a review decision and record what you checked.")
        record["review"] = {"actor": actor, "note": note.strip(), "decision": decision,
                            "annotation_sha256": annotation_digest(annotation)}
    else:
        raise ValueError("Unknown action.")
    return record


def duplicate_candidates(rows):
    for a, b in combinations(rows, 2):
        one, two = a["signature"], b["signature"]
        if a["original_sha256"] == b["original_sha256"] or one["pixel_sha256"] == two["pixel_sha256"]:
            yield a["id"], b["id"], "exact"
        elif (
            min(a["width"] * b["height"], b["width"] * a["height"])
            >= .9 * max(a["width"] * b["height"], b["width"] * a["height"])
            and (one["phash"] ^ two["phash"]).bit_count() <= 6
            and (one["dhash"] ^ two["dhash"]).bit_count() <= 6
        ):
            yield a["id"], b["id"], "near"


def practice_ids(root):
    for roster in (root / "practice" / "roster.json", root / "practice_only.json"):
        if roster.is_file():
            return set(read_json(roster))
    return set()


def prepare_practice(root):
    destination = root / "practice"
    if destination.exists() or (root / "practice_only.json").exists():
        raise ValueError("A practice roster already exists for this workspace.")
    candidates = [r for r in records(root).values() if r["split"] == "pool" and not r["annotation"]]
    if len(candidates) < 10:
        raise ValueError("Register at least ten unlabelled pool images for blind practice.")
    candidates.sort(key=lambda r: (r["source"], r["source_asset"]))
    choices = [candidates[i * len(candidates) // 10] for i in range(10)]
    identifiers = [r["id"] for r in choices]
    with TemporaryDirectory(dir=root) as tmp:
        stage = Path(tmp) / "practice"
        stage.mkdir(mode=0o700)
        for person in ("annotator-a", "annotator-b"):
            child = stage / person
            (child / "records").mkdir(mode=0o700, parents=True)
            (child / "images").mkdir(mode=0o700)
            write_json(child / "practice_only.json", identifiers)
            for r in choices:
                i = r["id"]
                source = root / "images" / f"{i}.png"
                if digest(source) != r["image_sha256"]:
                    raise ValueError(f"Practice image {i} differs from the registered file.")
                shutil.copyfile(source, child / "images" / source.name)
                write_json(child / "records" / f"{i}.json", {**r, "annotation": None, "review": None})
        write_json(stage / "roster.json", identifiers)
        stage.rename(destination)
    print("Prepared ten practice images in two independent annotation workspaces.")


def audit(root):
    rows = list(records(root).values())
    reserved = practice_ids(root)
    selected = [r for r in rows if r["split"] in SPLITS]
    practice_groups = {
        field: {r[field].casefold() for r in rows if r["id"] in reserved and r[field]} for field in ("device", "session")
    }
    assisted = {r["id"] for r in rows if r.get("model_assisted")}
    assisted_groups = {
        field: {r[field].casefold() for r in rows if r["id"] in assisted and r[field]} for field in ("device", "session")
    }
    groups = {field: defaultdict(set) for field in ("device", "session")}
    stats = {split: Counter({k: 0 for k in ("images", "annotated", "approved", "reviewed_clean", *CLASSES)})
             for split in ("pool", *SPLITS)}
    readiness = []
    for r in rows:
        s = stats[r["split"]]
        s["images"] += 1
        s["practice_reserved"] += r["id"] in reserved
        s["short_edge_below_640"] += min(r["width"], r["height"]) < 640
        s[f'source:{r["source"]}'] += 1
        s[f'view:{r["view"]}'] += 1
        annotation, review = r["annotation"], r["review"]
        s["annotated"] += bool(annotation)
        approved = approved_annotation(r)
        s["approved"] += approved
        if approved:
            s[f'reviewed_{annotation["kind"]}'] += 1
            s.update(b["label"] for b in annotation["boxes"])
    for r in selected:
        i = r["id"]
        if i in reserved:
            readiness.append(f"{i}: reserved for annotation practice")
        if i in assisted and r["split"] != "train":
            readiness.append(f"{i}: model-assisted photos may be used only for training")
        path = root / "images" / f"{i}.png"
        if not path.is_file() or digest(path) != r["image_sha256"]:
            readiness.append(f"{i}: missing or changed image")
        if not approved_annotation(r):
            readiness.append(f"{i}: independent approval of current annotation required")
        else:
            validate_annotation(r, r["annotation"])
            if r["annotation"]["kind"] == "exclude":
                readiness.append(f"{i}: excluded image")
        for field, lookup in groups.items():
            value = r[field]
            if not value:
                readiness.append(f"{i}: {field} provenance missing")
            else:
                lookup[value.casefold()].add(r["split"])
                if value.casefold() in practice_groups[field]:
                    readiness.append(f"{i}: {field} is shared with an annotation practice image")
                if r["split"] != "train" and value.casefold() in assisted_groups[field]:
                    readiness.append(f"{i}: {field} is shared with a model-assisted training image")
        if r["split"] == "test" and not r["overlap_evidence"].strip():
            readiness.append(f"{i}: test requires evidence of independence from both checkpoints")
    for field, lookup in groups.items():
        for group, splits in lookup.items():
            if len(splits) > 1:
                readiness.append(f"{field} {group} occurs across splits: {', '.join(sorted(splits))}")

    duplicate_file = root / "duplicate_reviews.json"
    reviews = read_json(duplicate_file) if duplicate_file.exists() else {}
    selected_ids = {r["id"] for r in selected}
    holdout_ids = {r["id"] for r in selected if r["split"] != "train"}
    duplicates = []
    by_id = {r["id"]: r for r in rows}
    for a, b, kind in duplicate_candidates(rows):
        rationale = reviews.get(f"{a}:{b}", "")
        accepted = kind == "near" and isinstance(rationale, str) and bool(rationale.strip())
        duplicate = {"a": a, "b": b, "kind": kind, "reviewed_distinct": accepted}
        first, second = by_id[a], by_id[b]
        if first.get("upstream_split") and second.get("upstream_split") and first["upstream_split"] != second["upstream_split"]:
            duplicate["different_upstream_splits"] = [first["upstream_split"], second["upstream_split"]]
        duplicates.append(duplicate)
        crosses_practice = (a in reserved and b in selected_ids) or (b in reserved and a in selected_ids)
        crosses_assisted = (a in assisted and b in holdout_ids) or (b in assisted and a in holdout_ids)
        if ((a in selected_ids and b in selected_ids) or crosses_practice or crosses_assisted) and not accepted:
            readiness.append(f"{kind} duplicate candidate {a}:{b}; remove a duplicate or review a near match")
    for split in SPLITS:
        subset = [r for r in selected if r["split"] == split]
        stats[split]["known_devices"] = len({r["device"].casefold() for r in subset if r["device"]})
        stats[split]["known_sessions"] = len({r["session"].casefold() for r in subset if r["session"]})
    test_groups, benchmark_blockers = benchmark_coverage([r for r in selected if r["split"] == "test"])
    findings = {
        "stats": {s: dict(c) for s, c in stats.items()},
        "duplicates": duplicates, "split_blockers": readiness,
        "test_class_and_clean_device_counts": test_groups,
        "benchmark_blockers": benchmark_blockers,
    }
    return findings, selected


def benchmark_coverage(test):
    devices, per_group, instances = set(), defaultdict(set), Counter()
    for row in test:
        if not row["device"] or not approved_annotation(row):
            continue
        group = row["device"].casefold()
        devices.add(group)
        if row["annotation"]["kind"] == "clean":
            per_group["clean"].add(group)
        for box in row["annotation"]["boxes"]:
            name = box["label"]
            instances[name] += 1
            per_group[name].add(group)
    groups = {label: len(per_group[label]) for label in (*CLASSES, "clean")}
    thresholds = (
        ("known devices", 30, len(devices)),
        ("crack instances", 30, instances["generic_crack"]),
        ("scratch instances", 30, instances["scratch"]),
        *((f"devices with {label}", 15, count) for label, count in groups.items()),
    )
    blockers = [f"test needs at least {minimum} {label}; found {count}"
                for label, minimum, count in thresholds if count < minimum]
    if not test:
        blockers.append("no test split")
    return groups, blockers


def label_text(record):
    w, h = record["width"], record["height"]
    lines = []
    for box in record["annotation"]["boxes"]:
        x1, y1, x2, y2 = box["xyxy"]
        norm = ((x1 + x2) / (2 * w), (y1 + y2) / (2 * h), (x2 - x1) / w, (y2 - y1) / h)
        lines.append(f"{CLASSES.index(box['label'])} " + " ".join(f"{value:.12g}" for value in norm) + "\n")
    return "".join(lines)


def review_queue(root):
    reserved = practice_ids(root)
    queue = {name: [] for name in ("practice", "check_provenance", "annotate", "revise", "independent_review", "approved")}
    for i, row in records(root).items():
        review = row["review"]
        if i in reserved:
            task = "practice"
        elif row["split"] == "pool" or not all(row[f] for f in ("device", "session")) or (
            row["split"] == "test" and not row["overlap_evidence"].strip()
        ):
            task = "check_provenance"
        elif not row["annotation"]:
            task = "annotate"
        elif approved_annotation(row):
            task = "approved"
        elif review and review["decision"] == "revise":
            task = "revise"
        else:
            task = "independent_review"
        queue[task].append(i)
    return queue


def export(root, output):
    findings, rows = audit(root)
    if not rows or findings["split_blockers"]:
        raise ValueError("No verified split export is possible. Run audit and resolve the split blockers.")
    output.mkdir(mode=0o700)
    manifest = {"schema": 1, "audit": findings, "splits": {}}
    config = {"names": list(CLASSES)}
    for split in SPLITS:
        manifest["splits"][split] = []
        subset = [r for r in rows if r["split"] == split]
        if not subset:
            continue
        config[split] = f"images/{split}"
        for folder in ("images", "labels"):
            (output / folder / split).mkdir(parents=True)
        for r in subset:
            i = r["id"]
            image = output / "images" / split / f"{i}.png"
            label = output / "labels" / split / f"{i}.txt"
            shutil.copyfile(root / "images" / image.name, image)
            label.write_text(label_text(r), encoding="utf-8")
            manifest["splits"][split].append({**r, "label_sha256": digest(label)})
    write_json(output / "manifest.json", manifest)
    # JSON is valid YAML, so the standard detector tools can consume this file.
    write_json(output / "data.yaml", config)


def catalog(root):
    import sys

    fields = ("id", "source_asset", "view", *PROVENANCE, *OPTIONAL_PROVENANCE)
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(records(root).values())


def apply_catalog(root, table):
    current = records(root)
    changes = {}
    with table.open(newline="", encoding="utf-8") as stream:
        csv_rows = csv.DictReader(stream)
        if not {"id", *PROVENANCE} <= set(csv_rows.fieldnames or ()):
            raise ValueError("Expected the ID and provenance columns produced by catalog.")
        for row in csv_rows:
            ident = key(row["id"])
            if ident not in current or ident in changes:
                raise ValueError(f"Unknown or repeated image ID: {ident}.")
            if any(row[field] is None for field in PROVENANCE):
                raise ValueError(f"Missing provenance fields in row {ident}.")
            fields = {field: row[field].strip() for field in PROVENANCE}
            if fields["split"] not in ("pool", *SPLITS):
                raise ValueError(f"Invalid split for {ident}.")
            for field in ("device", "session"):
                if fields[field]:
                    key(fields[field])
            for field in OPTIONAL_PROVENANCE:
                if field in row and row[field] is not None:
                    fields[field] = row[field].strip()
            if fields.get("capture_date"):
                capture_date(fields["capture_date"])
            changes[ident] = fields
    for ident, fields in changes.items():
        current[ident].update(fields)
        write_json(root / "records" / f"{ident}.json", current[ident])
    print(f"Updated provenance for {len(changes)} images.")

def capture_date(value):
    if value and date.fromisoformat(value).isoformat() != value:
        raise ValueError("Capture dates must use YYYY-MM-DD.")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Private directory outside this checkout")
    commands = parser.add_subparsers(dest="cmd", required=True)
    broken = commands.add_parser("import-broken")
    broken.add_argument("checkout", type=Path)
    add = commands.add_parser("add")
    add.add_argument("image", type=Path)
    for field in ("source", "asset", "license", "attribution"):
        add.add_argument(f"--{field}", required=True)
    add.add_argument("--view", required=True, choices=("front", "back", "camera", "left_side", "right_side"))
    meta = commands.add_parser("meta")
    meta.add_argument("id")
    meta.add_argument("--split", choices=("pool", *SPLITS))
    meta.add_argument("--device", type=key)
    meta.add_argument("--session", type=key)
    meta.add_argument("--overlap-evidence")
    meta.add_argument("--capture-date", type=capture_date)
    meta.add_argument("--permission-ref")
    commands.add_parser("prepare-practice")
    commands.add_parser("audit")
    commands.add_parser("queue")
    commands.add_parser("catalog")
    commands.add_parser("apply-catalog").add_argument("table", type=Path)
    out = commands.add_parser("export")
    out.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        root = private_path(args.root)
        if args.cmd == "import-broken":
            import subprocess

            expected = BI_URL.rsplit("/", 1)[-1]
            actual = subprocess.check_output(["git", "-C", str(args.checkout), "rev-parse", "HEAD"], text=True).strip()
            if actual != expected:
                raise ValueError("Expected the audited Broken Interfaces revision.")
            folder = args.checkout / "phone_cropped_display"
            files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
            if len(files) != 95:
                raise ValueError("Expected 95 display crops at the audited revision.")
            for path in files:
                relative = path.relative_to(args.checkout).as_posix()
                # Check working files against Git so the pinned source cannot be silently substituted.
                published = subprocess.check_output(["git", "-C", str(args.checkout), "show", f"HEAD:{relative}"])
                if hashlib.sha256(published).hexdigest() != digest(path):
                    raise ValueError("Broken Interfaces crop differs from the audited source.")
                register(root, path, BI_URL, relative, "CC BY 4.0 https://creativecommons.org/licenses/by/4.0/", BI_ATTRIBUTION, "front")
            print(f"Registered {len(files)} unlabelled display crops in the pool.")
        elif args.cmd == "add":
            print(register(root, args.image, args.source, args.asset, args.license, args.attribution, args.view))
        elif args.cmd == "meta":
            path = root / "records" / f"{key(args.id)}.json"
            record = read_json(path)
            for field in (*PROVENANCE, *OPTIONAL_PROVENANCE):
                if getattr(args, field) is not None:
                    record[field] = getattr(args, field)
            write_json(path, record)
        elif args.cmd == "prepare-practice":
            prepare_practice(root)
        elif args.cmd == "catalog":
            catalog(root)
        elif args.cmd == "apply-catalog":
            apply_catalog(root, private_path(args.table))
        elif args.cmd == "queue":
            print(json.dumps(review_queue(root), indent=2))
        elif args.cmd == "audit":
            findings, _ = audit(root)
            print(json.dumps(findings, indent=2))
        else:
            export(root, private_path(args.output))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
