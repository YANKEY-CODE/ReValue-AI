"""Regression checks using only generated software fixtures."""

from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from dataset import audit, export, prepare_practice, practice_ids, read_json, register, review_queue, update_record, write_json
from evaluate import BUNDLED_SHA, frozen_test, match
from propose import proposal_for


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def record(self, asset, color="grey", variant=False):
        path = self.root / f"{asset}.png"
        image = Image.new("RGB", (64, 64), color)
        if variant:
            ImageDraw.Draw(image).rectangle((8, 8, 24, 31), fill="black")
        image.save(path)
        i = register(self.root, path, "software-fixture", asset, "n/a", "synthetic", "front")
        return self.root / "records" / f"{i}.json"

    def approved(self, path, split, device, session, clean=False):
        row = read_json(path)
        boxes = [] if clean else [{"label": "generic_crack", "xyxy": [1, 1, 30, 20]}]
        update_record(row, "annotate", dict(actor="author", kind="clean" if clean else "positive", boxes=boxes, note="fixture"))
        update_record(row, "review", dict(actor="reviewer", decision="approved", note="fixture"))
        row.update(split=split, device=device, session=session, overlap_evidence="fixture only")
        write_json(path, row)

    def test_invalid_annotations_and_self_review(self):
        row = read_json(self.record("one"))
        for label, box in (("bump", [1, 1, 30, 30]), ("scratch", [4, 2, 65, 8]), ("scratch", [2, 2, 2, 8])):
            with self.assertRaises(ValueError):
                update_record(row, "annotate", dict(actor="author", kind="positive", note="fixture",
                                                   boxes=[{"label": label, "xyxy": box}]))
        update_record(row, "annotate", dict(actor="author", kind="clean", boxes=[], note="fixture"))
        with self.assertRaisesRegex(ValueError, "independent"):
            update_record(row, "review", dict(actor="Author", decision="approved", note="fixture"))
        update_record(row, "review", dict(actor="other", decision="approved", note="fixture"))
        update_record(row, "annotate", dict(actor="author", kind="exclude", boxes=[], note="fixture"))
        self.assertIsNone(row["review"])

    def test_duplicate_and_device_session_leakage(self):
        a, b = self.record("one"), self.record("two")
        self.approved(a, "train", "same-phone", "same-session")
        self.approved(b, "test", "same-phone", "same-session")
        result, _ = audit(self.root)
        problems = "\n".join(result["split_blockers"])
        self.assertIn("device same-phone occurs across splits", problems)
        self.assertIn("session same-session occurs across splits", problems)
        self.assertIn("exact duplicate", problems)
        with self.assertRaises(ValueError):
            export(self.root, self.root / "invalid")

    def test_export_creates_verified_negative_but_does_not_admit_tiny_test(self):
        a = self.record("damage", variant=True)
        b = self.record("clean")
        self.approved(a, "test", "phone-1", "session-1")
        self.approved(b, "test", "phone-2", "session-2", clean=True)
        out = self.root / "export"
        export(self.root, out)
        self.assertEqual((out / "labels/test" / f"{b.stem}.txt").read_text(), "")
        self.assertTrue((out / "labels/test" / f"{a.stem}.txt").read_text().startswith("0 "))
        with self.assertRaisesRegex(ValueError, "Benchmark is blocked"):
            frozen_test(out)

    def test_practice_workspaces_are_independent_and_reserved(self):
        inputs = [self.record(f"practice-{index}", color=(index * 20, 50, 100)) for index in range(10)]
        prepare_practice(self.root)
        first, second = (self.root / "practice" / f"annotator-{letter}" for letter in ("a", "b"))
        self.assertEqual(practice_ids(first), practice_ids(second))
        self.assertEqual(len(practice_ids(first)), 10)
        name = inputs[0].name
        self.approved(first / "records" / name, "test", "fixture-phone", "fixture-session", clean=True)
        self.assertIsNone(read_json(second / "records" / name)["annotation"])
        self.assertIsNone(read_json(inputs[0])["annotation"])
        self.approved(inputs[0], "test", "fixture-phone", "fixture-session", clean=True)
        findings, _ = audit(self.root)
        self.assertIn(f"{inputs[0].stem}: reserved for annotation practice", findings["split_blockers"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            prepare_practice(self.root)

    def test_proposals_separate_from_training_labels_and_excluded_from_holdout(self):
        path = self.record("training-image")
        row = read_json(path)
        self.assertEqual(review_queue(self.root)["check_provenance"], [row["id"]])
        row.update(split="train", device="phone-1", session="session-1", model_assisted=True)
        write_json(path, row)
        (self.root / "proposals").mkdir()
        box = {"label": "generic_crack", "xyxy": [1, 1, 10, 10], "confidence": .8}
        write_json(self.root / "proposals" / path.name, {
            "id": row["id"], "image_sha256": row["image_sha256"], "weights_sha256": BUNDLED_SHA, "boxes": [box],
        })
        self.assertEqual(proposal_for(self.root, row["id"]), [box])
        self.assertIsNone(read_json(path)["annotation"])
        self.assertIsNone(read_json(path)["review"])
        self.assertEqual(review_queue(self.root)["annotate"], [row["id"]])
        self.approved(path, "test", "phone-1", "session-1")
        with self.assertRaisesRegex(ValueError, "training image"):
            proposal_for(self.root, row["id"])
        self.assertTrue(any("model-assisted" in item for item in audit(self.root)[0]["split_blockers"]))

    def test_editing_saved_approval_and_clearing_manifest_blockers_cannot_unlock_benchmark(self):
        path = self.record("damage")
        self.approved(path, "test", "phone-1", "session-1")
        out = self.root / "export"
        export(self.root, out)
        manifest = read_json(out / "manifest.json")
        manifest["audit"]["benchmark_blockers"] = []
        write_json(out / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "do not meet"):
            frozen_test(out)
        row = read_json(path)
        row["annotation"]["boxes"][0]["xyxy"] = [2, 2, 20, 20]
        write_json(path, row)
        self.assertEqual(review_queue(self.root)["independent_review"], [row["id"]])
        self.assertIn(f'{row["id"]}: independent approval of current annotation required',
                      audit(self.root)[0]["split_blockers"])

    def test_class_aware_one_to_one_matching(self):
        targets = [(0, 0, 20, 20, "generic_crack"), (40, 40, 60, 60, "scratch")]
        predictions = [(0, 0, 20, 20, "scratch", .95), (0, 0, 20, 20, "generic_crack", .9),
                       (0, 0, 20, 20, "generic_crack", .8), (40, 40, 60, 60, "scratch", .7)]
        self.assertEqual(match(targets, predictions, .5), {1: 0, 3: 1})


if __name__ == "__main__":
    unittest.main()
