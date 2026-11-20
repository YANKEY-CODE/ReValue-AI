"""Software fixtures for grouped proposals, explicit manifests and integrity gates."""
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from pipeline import prepare
from dataset import export, read_json, register, update_record, write_json
from split_plan import propose


def fixture_export(directory):
    pool = directory / "pool"
    rng = np.random.default_rng(17)
    for split, count in (("train", 4), ("val", 2), ("test", 45)):
        for i in range(count):
            asset = f"{split}-{i}"
            image = directory / "fixture.png"
            Image.fromarray(rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)).save(image)
            ident = register(pool, image, "generated software fixtures", asset, "fixture", "test suite", "front")
            path = pool / "records" / (ident + ".json")
            row = read_json(path)
            clean = i >= 30 if split == "test" else i % 2 == 1
            boxes = [] if clean else [{"label": "scratch", "xyxy": [5, 8, 22, 26]},
                                      {"label": "generic_crack", "xyxy": [30, 32, 52, 57]}]
            update_record(row, "annotate", dict(kind="clean" if clean else "positive",
                                                 boxes=boxes, actor="fixture-a", note="software only"))
            update_record(row, "review", dict(decision="approved", actor="fixture-b", note="software only"))
            row.update(split=split, device=asset, session=asset, overlap_evidence="synthetic fixture only")
            write_json(path, row)
    root = directory / "export"
    export(pool, root)
    return root


class PipelineTests(unittest.TestCase):
    def test_explicit_paths_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            root = fixture_export(directory)
            extra = root / "images/train/unreviewed.png"
            extra.write_bytes(b"unreviewed fixture")
            work = directory / "work"
            prepare(root, work)
            listing = (work / "train.txt").read_text().splitlines()
            self.assertEqual(len(listing), 4)
            self.assertNotIn(str(extra), listing)
            Path(listing[0]).write_bytes(b"changed fixture")
            with self.assertRaisesRegex(ValueError, "changed"):
                prepare(root, work)

    def test_transitive_groups_and_practice(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = read_json(fixture_export(Path(tmp)) / "manifest.json")
            rows = manifest["splits"]["train"]
            for row in rows:
                row.update(split="pool")
            rows[0].update(device="A", session="X", model_assisted=True)
            rows[1].update(device="B", session="X")
            rows[2].update(device="B", session="Y")
            result = propose(rows, {rows[3]["id"]})
            self.assertEqual({r["id"] for r in result}, {r["id"] for r in rows[:3]})
            self.assertTrue(all(r["split"] == "train" for r in result))
            self.assertEqual(result, propose(rows[::-1], {rows[3]["id"]}))
            self.assertFalse(propose(rows, {rows[0]["id"], rows[3]["id"]}))
