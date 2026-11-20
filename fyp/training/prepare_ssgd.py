"""Inspect and import the official SSGD ZIP into a private ReValue review pool."""

import argparse
from collections import Counter
from contextlib import redirect_stdout
import os
from pathlib import Path, PureWindowsPath
import shutil
import stat
import sys
from tempfile import mkdtemp
from zipfile import BadZipFile, ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))

from dataset import audit, catalog, digest, private_path, read_json, records, review_queue, write_json
from import_dataset import coco_entries, image_scan, import_references, within

SOURCE = "https://github.com/VincentHancoder/SSGD/tree/2004178e4ff0cb61787e4940b871f1e5e2645c29"
LICENSE = "SSGD authors permit academic use only. " + SOURCE
ATTRIBUTION = "Haonan Han, Rui Yang, Shuyan Li, Runze Hu and Xiu Li. SSGD: A Smartphone Screen Glass Dataset for Defect Detection. ICASSP 2023."
TARGETS = {"crack": "generic_crack", "scratch": "scratch"}
SUBSETS = ("lb101", "lb201")


def extract_archive(archive, output):
    with ZipFile(archive) as source:
        members = source.infolist()
        names = set()
        for entry in members:
            name = entry.filename.rstrip("/")
            parts = name.split("/")
            if any(
                not part or part in (".", "..") or part.endswith((" ", "."))
                or PureWindowsPath(part).is_reserved() or any(c in part for c in ':\\<>|"*?')
                for part in parts
            ) or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError(f"Unsafe ZIP member: {entry.filename!r}")
            folded = name.casefold()
            if folded in names:
                raise ValueError(f"Duplicate ZIP member (case insensitive): {entry.filename!r}")
            names.add(folded)
        size = sum(entry.file_size for entry in members)
        if size >= shutil.disk_usage(output.parent).free:
            raise ValueError(f"Not enough free space for {size:,} bytes of ZIP contents.")
        source.extractall(output, members)
        return {"members": len(members), "uncompressed_bytes": size}


def find_splits(root):
    for subset in SUBSETS:
        candidates = sorted(
            path for path in root.rglob(f"images_{subset}")
            if path.is_dir() and (path.parent / "annotations" / subset).is_dir()
        )
        if len(candidates) > 1:
            raise ValueError(f"Multiple copies of {subset} found. Use a single official archive.")
        if not candidates:
            continue
        images = candidates[0]
        for split in ("train", "val"):
            annotations = images.parent / "annotations" / subset / f"{split}1.json"
            if not annotations.is_file():
                raise ValueError(f"Missing expected fold 1 file: {annotations.relative_to(root)}")
            yield subset, split, images, annotations


def prepare(archive, work, permission_ref):
    archive_sha = digest(archive)
    extracted = work / "extracted"
    pool = work / "pool"
    report = {"archive_sha256": archive_sha, "source": SOURCE, "license_terms": LICENSE,
              "permission_ref": permission_ref, "archive_inventory": extract_archive(archive, extracted)}
    splits = list(find_splits(extracted))
    if not splits:
        raise ValueError("No official layout found. Inspect the extracted directory for annotations/lb101 or lb201 and corresponding images folders.")

    all_cohort_images = set()
    listed_images = Counter()
    source_counts = Counter()
    unique_annotations = set()
    intake = []
    for subset, split, images, annotations in splits:
        config = read_json(annotations)
        categories = {row["id"]: row["name"] for row in config["categories"]}
        paths = {r["id"]: within(extracted, images / r["file_name"]).relative_to(extracted).as_posix()
                 for r in config["images"]}
        counts = Counter(categories[r["category_id"]] for r in config["annotations"])
        source_counts.update(counts)
        listed_images.update(paths.values())
        all_cohort_images.update(p.relative_to(extracted).as_posix() for p in image_scan(images))
        for r in config["annotations"]:
            unique_annotations.add((paths[r["image_id"]], categories[r["category_id"]], tuple(r["bbox"])))
        mapped = {name: TARGETS[name.strip().casefold()] for name in categories.values()
                  if name.strip().casefold() in TARGETS}
        metadata = {
            "source": SOURCE, "version": "ssgd-" + archive_sha, "license": LICENSE,
            "attribution": ATTRIBUTION, "view": "front", "format": "coco",
            "permission_ref": permission_ref, "upstream_split": f"{subset}-fold1-{split}",
            "source_annotation_sha256": digest(annotations),
        }
        result = import_references(pool, extracted, coco_entries(extracted, annotations, images, mapped), metadata)
        intake.append({"annotations": annotations.relative_to(extracted).as_posix(),
                       "source_images": len(config["images"]), "source_boxes_by_class": dict(counts),
                       "declared_classes": list(categories.values()), "mapped_classes": mapped, **result})

    proposed = Counter(
        box["proposed_class"]
        for filename in (pool / "source_references").glob("*.json")
        for box in read_json(filename)["boxes"]
        if box["proposed_class"] is not None
    )
    findings, _ = audit(pool)
    write_json(work / "audit.json", findings)
    write_json(work / "review-queue.json", review_queue(pool))
    # This file can be filled with verified metadata and applied through dataset.py.
    with (work / "provenance.csv").open("w", encoding="utf-8", newline="") as stream:
        with redirect_stdout(stream):
            catalog(pool)
    report.update(
        intake=intake, unique_cohort_image_files=len(all_cohort_images),
        unique_fold1_annotation_image_paths=len(listed_images), raw_fold1_annotation_rows=sum(source_counts.values()),
        unique_fold1_image_class_box_signatures=len(unique_annotations),
        raw_boxes_by_class=dict(source_counts), unique_classes=sorted({c for part in intake for c in part["declared_classes"]}),
        repeated_fold1_image_paths=sorted(path for path, count in listed_images.items() if count > 1),
        cohort_images_absent_from_fold1_json=sorted(all_cohort_images - listed_images.keys()),
        registered_pool_images=len(records(pool)), proposed_boxes_by_class={c: proposed[c] for c in TARGETS.values()},
        duplicate_candidates=len(findings["duplicates"]), approved_images=sum(s["approved"] for s in findings["stats"].values()),
    )
    write_json(work / "intake.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-parent", type=Path, required=True,
                        help="Dedicated private directory outside this repository")
    parser.add_argument("--permission-ref", required=True, help="Private reference to the file origin and academic permission")
    args = parser.parse_args()
    if not args.permission_ref.strip():
        parser.error("Provide a non-empty permission reference.")
    work = None
    try:
        archive = private_path(args.archive)
        if not archive.is_file():
            raise ValueError("Archive file was not found.")
        parent = private_path(args.output_parent)
        parent.mkdir(parents=True, exist_ok=True)
        work = Path(mkdtemp(prefix="ssgd-", dir=parent))
        print(f"Private intake directory: {work}", flush=True)
        report = prepare(archive, work, args.permission_ref)
        print(f'{report["unique_cohort_image_files"]} image files in recognized subsets, '
              f'{report["raw_fold1_annotation_rows"]} annotation rows and {len(report["unique_classes"])} classes in fold 1.')
        print(f'{report["registered_pool_images"]} images registered for review; '
              f'{report["approved_images"]} approved. See intake.json and audit.json.')
        if (not report["registered_pool_images"] or report["repeated_fold1_image_paths"]
                or any(part["issues"] for part in report["intake"])):
            raise SystemExit(1)
    except (ValueError, TypeError, KeyError, OSError, BadZipFile) as exc:
        if work is not None:
            write_json(work / "error.json", {"error": str(exc)})
        parser.error(str(exc))


if __name__ == "__main__":
    if os.name != "nt":
        os.umask(0o077)
    main()
