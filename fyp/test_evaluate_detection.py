"""Dataset and metric regressions. Generated images here are software fixtures."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from evaluate_detection import audit_dataset, scores


class EvaluationTests(unittest.TestCase):
    def test_metrics_include_false_positives_and_misses(self):
        self.assertEqual(scores(2, 4, 5), {
            "precision": 0.5, "recall": 0.4, "f1": 4 / 9, "tp": 2, "fp": 2, "fn": 3, "targets": 5,
        })
        self.assertEqual(scores(0, 0, 2)["f1"], 0)

    def test_audit_requires_reviewed_negatives_and_both_classes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("images/test", "labels/test", "images/train"):
                (root / folder).mkdir(parents=True)
            for i, color in enumerate(("white", "grey", "black")):
                Image.new("RGB", (64, 64), color).save(root / "images/test" / f"{i}.png")
            labels = root / "labels/test"
            (labels / "0.txt").write_text("0 .5 .5 .2 .2\n")
            (labels / "1.txt").write_text("1 .5 .5 .2 .2\n")
            config = {"names": ["generic_crack", "scratch"], "test": "images/test"}
            with self.assertRaisesRegex(ValueError, "Missing box annotation"):
                audit_dataset(config, root / "data.yaml")
            (labels / "2.txt").touch()
            _, counts, negatives, fingerprint = audit_dataset(config, root / "data.yaml")
            self.assertEqual((counts, negatives, len(fingerprint)), ([1, 1], 1, 64))
            (labels / "1.txt").write_text("")
            with self.assertRaisesRegex(ValueError, "both crack and scratch"):
                audit_dataset(config, root / "data.yaml")
            (labels / "1.txt").write_text("1 .5 .5 .2 .2\n")
            (root / "images/train/duplicate.png").write_bytes((root / "images/test/0.png").read_bytes())
            with self.assertRaisesRegex(ValueError, "also occurs in train"):
                audit_dataset(config | {"train": "images/train"}, root / "data.yaml")


if __name__ == "__main__":
    unittest.main()
