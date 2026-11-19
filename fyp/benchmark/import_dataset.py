"""Import authorized COCO, YOLO or Pascal VOC exports as unverified references."""

import argparse
from collections import Counter
import math
import os
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image
import yaml

from dataset import CLASSES, digest, private_path, read_json, register, write_json

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def within(root, path):
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ValueError("Dataset path escapes its source directory.")
    return path


def dimensions(path):
    with Image.open(path) as image:
        if image.getexif().get(274, 1) != 1:
            raise ValueError("Normalize image orientation and its labels together before import.")
        if getattr(image, "n_frames", 1) != 1 or image.width * image.height > 24_000_000 or min(image.size) < 10:
            raise ValueError("Expected one still image between 10 px per edge and 24 megapixels.")
        size = image.size
        image.load()
    return size


def box_record(label, coords, width, height, mapping):
    x1, y1, x2, y2 = map(float, coords)
    if not all(math.isfinite(v) for v in (x1, y1, x2, y2)) or not (
        0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height
    ):
        raise ValueError(f"Out-of-bounds or degenerate box for {label}.")
    return {"source_label": label, "proposed_class": mapping.get(label), "xyxy": [x1, y1, x2, y2]}


def coco_entries(root, annotation_path, images_dir, mapping):
    config = read_json(annotation_path)
    counts = Counter(row["id"] for row in config["images"])
    if any(n != 1 for n in counts.values()):
        raise ValueError("Repeated COCO image ID.")
    categories = {row["id"]: row["name"] for row in config["categories"]}
    if len(categories) != len(config["categories"]):
        raise ValueError("Repeated COCO category ID.")
    grouped = {i: [] for i in counts}
    used = set()
    for obj in config["annotations"]:
        if obj["id"] in used or obj["image_id"] not in grouped or obj["category_id"] not in categories:
            raise ValueError("Repeated COCO annotation ID or unresolved image/category reference.")
        used.add(obj["id"])
        grouped[obj["image_id"]].append(obj)
    for row in config["images"]:
        path = within(root, images_dir / row["file_name"])

        def read(size, row=row):
            if tuple(size) != (row["width"], row["height"]):
                raise ValueError("COCO and actual image dimensions differ.")
            boxes = []
            ignored = 0
            for obj in grouped[row["id"]]:
                if obj.get("iscrowd") or obj.get("ignore"):
                    ignored += 1
                    continue
                x, y, w, h = map(float, obj["bbox"])
                boxes.append(box_record(categories[obj["category_id"]], (x, y, x+w, y+h), *size, mapping))
            return {"status": "boxes" if boxes else "empty_unverified", "boxes": boxes, "ignored": ignored}

        yield path, read


def image_scan(folder):
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in EXTENSIONS)


def yolo_entries(root, annotation_path, split, mapping):
    cfg = yaml.safe_load(annotation_path.read_text(encoding="utf-8"))
    values = cfg.get("names")
    names = dict(enumerate(values)) if isinstance(values, list) else {int(k): v for k, v in values.items()}
    base = within(root, annotation_path.parent / cfg.get("path", "."))
    entries = cfg[split]
    folders = [entries] if isinstance(entries, str) else entries
    if not isinstance(folders, list) or not folders:
        raise ValueError("Expected local YOLO image directories in the selected split.")
    for entry in folders:
        folder = within(root, base / entry)
        if not folder.is_dir():
            raise ValueError("YOLO text-list splits are not accepted; supply image directories.")
        for path in image_scan(folder):
            parts = list(path.relative_to(root).parts)
            if "images" not in parts[:-1]:
                raise ValueError("Expected a YOLO images directory with matching labels directory.")
            last_images = max(i for i, part in enumerate(parts[:-1]) if part == "images")
            parts[last_images] = "labels"
            label_path = within(root, root.joinpath(*parts).with_suffix(".txt"))

            def read(size, label_path=label_path):
                if not label_path.is_file():
                    return {"status": "missing", "boxes": []}
                width, height = size
                boxes = []
                for line in label_path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    cls, x, y, w, h = line.split()
                    x, y, w, h = map(float, (x, y, w, h))
                    # Tolerate tiny floating-point roundoff at the normalized borders only.
                    edges = ((x-w/2)*width, (y-h/2)*height, (x+w/2)*width, (y+h/2)*height)
                    bounds = (width, height, width, height)
                    corners = tuple(0 if abs(value) < 1e-7 else end if abs(value-end) < 1e-7 else value
                                    for value, end in zip(edges, bounds, strict=True))
                    boxes.append(box_record(names[int(cls)], corners, width, height, mapping))
                return {"status": "boxes" if boxes else "empty_unverified", "boxes": boxes,
                        "source_label_sha256": digest(label_path)}

            yield within(root, path), read


def voc_entries(root, images, annotations, mapping):
    for path in image_scan(images):
        label_path = within(root, annotations / path.relative_to(images).with_suffix(".xml"))

        def read(size, label_path=label_path):
            if not label_path.is_file():
                return {"status": "missing", "boxes": []}
            if label_path.stat().st_size > 2_000_000:
                raise ValueError("VOC XML is unexpectedly large.")
            xml = ElementTree.parse(label_path).getroot()
            if size != (int(xml.findtext("size/width")), int(xml.findtext("size/height"))):
                raise ValueError("VOC and actual image dimensions differ.")
            boxes, ignored = [], 0
            for obj in xml.findall("object"):
                if obj.findtext("difficult") == "1":
                    ignored += 1
                    continue
                x1, y1, x2, y2 = [int(obj.findtext("bndbox/" + field)) for field in ("xmin", "ymin", "xmax", "ymax")]
                if not obj.findtext("name"):
                    raise ValueError("VOC object has no class name.")
                # Standard VOC pixel indices are one-based and inclusive.
                boxes.append(box_record(obj.findtext("name"), (x1-1, y1-1, x2, y2), *size, mapping))
            return {"status": "boxes" if boxes else "empty_unverified", "boxes": boxes, "ignored": ignored,
                    "source_label_sha256": digest(label_path)}

        yield within(root, path), read


def import_references(root, source_root, entries, metadata):
    sidecars = root / "source_references"
    sidecars.mkdir(mode=0o700, parents=True, exist_ok=True)
    report = {"imported": 0, "issues": [], "statuses": {}}
    statuses = Counter()
    seen = set()
    for path, decode in entries:
        relative = path.relative_to(source_root).as_posix()
        try:
            if relative in seen:
                raise ValueError("Repeated image path in this import.")
            seen.add(relative)
            reference = decode(dimensions(path))
            ident = register(root, path, metadata["source"], f'{metadata["version"]}/{relative}',
                             metadata["license"], metadata["attribution"], metadata["view"])
            rpath = root / "records" / f"{ident}.json"
            row = read_json(rpath)
            ref = {**reference, **metadata, "source_asset": relative, "image_sha256": row["image_sha256"],
                   "authority": "unverified_source_annotations"}
            output = sidecars / f"{ident}.json"
            if output.exists() and read_json(output) != ref:
                raise ValueError("Existing source reference changed. Create a new source version.")
            write_json(output, ref)
            row.update(source_version=metadata["version"], upstream_split=metadata["upstream_split"],
                       permission_ref=metadata["permission_ref"])
            write_json(rpath, row)
            report["imported"] += 1
            statuses[ref["status"]] += 1
        except (ValueError, TypeError, OSError, KeyError, SyntaxError, ElementTree.ParseError) as exc:
            report["issues"].append({"source_asset": relative, "reason": str(exc)})
    report["statuses"] = dict(statuses)
    return report


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "source-root", "annotations", "report"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--images", type=Path, default=Path("images"))
    parser.add_argument("--format", choices=("coco", "yolo", "voc"), required=True)
    for name in ("source", "version", "license", "attribution", "permission-ref", "upstream-split"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--view", choices=("front", "back", "camera", "left_side", "right_side", "unknown"), default="unknown")
    parser.add_argument("--map", action="append", default=[], metavar="SOURCE=TARGET")
    args = parser.parse_args()
    try:
        root = private_path(args.root)
        config_root = private_path(args.source_root)
        if root.is_relative_to(config_root) or config_root.is_relative_to(root):
            raise ValueError("Use separate source and benchmark directories.")
        annotations = within(config_root, config_root / args.annotations)
        images = within(config_root, config_root / args.images)
        output = private_path(args.report)
        if output.exists():
            raise ValueError("Choose a new report path.")
        mapping = dict(item.split("=", 1) for item in args.map)
        if any(not name.strip() or label not in CLASSES for name, label in mapping.items()):
            raise ValueError("Map source class names explicitly to generic_crack or scratch.")
        if args.format == "coco":
            entries = coco_entries(config_root, annotations, images, mapping)
        elif args.format == "yolo":
            entries = yolo_entries(config_root, annotations, args.upstream_split, mapping)
        else:
            entries = voc_entries(config_root, images, annotations, mapping)
        metadata = {field: getattr(args, field) for field in (
            "source", "version", "license", "attribution", "permission_ref", "upstream_split", "view", "format"
        )}
        if any(not value.strip() for value in metadata.values()):
            raise ValueError("Specify non-empty source and rights metadata.")
        if annotations.is_file():
            metadata["source_annotation_sha256"] = digest(annotations)
        result = import_references(root, config_root, entries, metadata)
        write_json(output, result)
        print(f"Imported {result['imported']} images as references; {len(result['issues'])} skipped. See the private report.")
        if not result["imported"] or result["issues"]:
            raise SystemExit(1)
    except (ValueError, TypeError, KeyError, OSError, yaml.YAMLError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
