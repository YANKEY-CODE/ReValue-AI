"""Propose reproducible device/session splits for a new private reviewed collection."""
import argparse
import csv
import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "benchmark"))
from dataset import PROVENANCE, approved_annotation, practice_ids, private_path, records


def propose(rows, reserved):
    # Include unlabelled bridge records when finding connected components.
    parents = {}

    def find(node):
        while node != parents.setdefault(node, node):
            parents[node] = parents[parents[node]]
            node = parents[node]
        return node

    def nodes(r):
        return [(k, r[k].casefold()) for k in ("device", "session") if r[k]]

    for r in rows:
        keys = nodes(r)
        if len(keys) == 2:
            a, b = sorted(map(find, keys))
            parents[b] = a
    groups = {}
    for r in rows:
        keys = nodes(r)
        if keys:
            groups.setdefault(find(keys[0]), []).append(r)
    changes = []
    for group, members in sorted(groups.items()):
        if any(r["id"] in reserved for r in members):
            continue
        eligible = [r for r in members if len(nodes(r)) == 2 and approved_annotation(r)
                    and r["annotation"]["kind"] != "exclude"]
        if not eligible:
            continue
        existing = {r["split"] for r in members if r["split"] != "pool"}
        if len(existing) > 1:
            raise ValueError("Existing assignments leak across a device/session component.")
        bucket = int.from_bytes(hashlib.sha256(("17|" + "|".join(group)).encode()).digest()[:8], "big") % 100
        split = next(iter(existing), "train" if bucket < 70 else "val" if bucket < 85 else "test")
        if any(r.get("model_assisted") for r in members):
            if existing - {"train"}:
                raise ValueError("Model-assisted component already occurs in a holdout.")
            split = "train"
        for r in eligible:
            if r["split"] == "pool" and (split != "test" or r["overlap_evidence"].strip()):
                changes.append({**r, "split": split})
    return sorted(changes, key=lambda r: r["id"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("proposal", type=Path)
    args = parser.parse_args()
    root = private_path(args.root)
    changes = propose(list(records(root).values()), practice_ids(root))
    with private_path(args.proposal).open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["id", *PROVENANCE], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(changes)
    print(f"{len(changes)} proposed assignments. Inspect before applying with dataset.py apply-catalog.")
