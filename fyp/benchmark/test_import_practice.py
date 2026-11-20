"""Fixtures for source imports and private offline practice exchanges."""

import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from dataset import audit, prepare_practice, read_json, register, write_json
from import_dataset import coco_entries, import_references, voc_entries, yolo_entries
from practice import compare, import_submission, inspect_submission, package, queue_records


class ImportAndPracticeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.destination = self.root / "target"
        self.inputs = self.root / "source"
        self.images = self.inputs / "images" / "train"
        self.images.mkdir(parents=True)
        self.image = self.images / "phone.png"
        Image.new("RGB", (120, 80), "grey").save(self.image)
        self.metadata = dict(source="fixture", version="v1", license="fixture", attribution="fixture",
                             view="front", permission_ref="fixture", upstream_split="train")

    def test_coco_checks_corruption_and_never_approves_source_boxes(self):
        (self.images / "bad.png").write_bytes(b"not an image")
        source = self.inputs / "objects.json"
        write_json(source, {
            "images": [{"id": index, "file_name": name, "width": 120, "height": 80}
                       for index, name in enumerate(("phone.png", "bad.png"), 1)],
            "categories": [{"id": 7, "name": "crack"}],
            "annotations": [{"id": 2, "image_id": 1, "category_id": 7, "bbox": [10, 20, 40, 15]}],
        })
        entries = coco_entries(self.inputs, source, self.images, {"crack": "generic_crack"})
        result = import_references(self.destination, self.inputs, entries, self.metadata)
        self.assertEqual((result["imported"], len(result["issues"])), (1, 1))
        ref = read_json(next((self.destination / "source_references").glob("*.json")))
        self.assertEqual(ref["boxes"][0]["xyxy"], [10, 20, 50, 35])
        self.assertEqual(ref["boxes"][0]["proposed_class"], "generic_crack")
        row = read_json(next((self.destination / "records").glob("*.json")))
        self.assertIsNone(row["annotation"])
        self.assertIsNone(row["review"])
        self.assertEqual(row["split"], "pool")
        self.assertEqual(row["device"], "")

    def test_yolo_keeps_missing_and_empty_separate_and_flags_upstream_overlap(self):
        labels = self.inputs / "labels" / "train"
        labels.mkdir(parents=True)
        (labels / "phone.txt").touch()
        second = self.images / "second.png"
        second.write_bytes(self.image.read_bytes())
        source = self.inputs / "data.yaml"
        write_json(source, {"names": {"0": "scratch"}, "train": "images/train"})
        entries = yolo_entries(self.inputs, source, "train", {"scratch": "scratch"})
        result = import_references(self.destination, self.inputs, entries, self.metadata)
        self.assertEqual(result["statuses"], {"empty_unverified": 1, "missing": 1})
        test = self.inputs / "images" / "test"
        test.mkdir()
        (test / "copy.png").write_bytes(self.image.read_bytes())
        write_json(source, {"names": ["scratch"], "test": "images/test"})
        entries = yolo_entries(self.inputs, source, "test", {})
        import_references(self.destination, self.inputs, entries, {**self.metadata, "upstream_split": "test"})
        findings, _ = audit(self.destination)
        self.assertEqual(len(findings["duplicates"]), 3)
        self.assertEqual(sum("different_upstream_splits" in row for row in findings["duplicates"]), 2)
        self.assertEqual(findings["stats"]["pool"]["approved"], 0)

    def test_voc_preserves_inclusive_coordinates_and_rejects_bad_extent(self):
        directory = self.inputs / "annotations"
        directory.mkdir()
        xml = directory / "phone.xml"
        xml.write_text("""<annotation><size><width>120</width><height>80</height></size>
          <object><name>scratch</name><bndbox><xmin>1</xmin><ymin>2</ymin><xmax>33</xmax><ymax>50</ymax></bndbox></object>
          </annotation>""")
        entries = voc_entries(self.inputs, self.images, directory, {"scratch": "scratch"})
        _, decode = next(entries)
        self.assertEqual(decode((120, 80))["boxes"][0]["xyxy"], [0, 1, 33, 50])
        xml.write_text(xml.read_text().replace("<xmax>33", "<xmax>130"))
        with self.assertRaisesRegex(ValueError, "Out-of-bounds"):
            decode((120, 80))

    def test_practice_import_hash_review_and_conflicts(self):
        for index in range(10):
            register(self.destination, self.image, "fixture", str(index), "fixture", "fixture", "front")
        prepare_practice(self.destination)
        package_file = self.root / "practice.html"
        package(self.destination, "annotator-b", package_file)
        html = package_file.read_text()
        self.assertIn('"queue":"annotator-b"', html)
        self.assertEqual(html.count("data:image/png;base64,"), 10)
        _, rows = queue_records(self.destination, "annotator-a")
        ident, row = next(iter(rows.items()))
        source = self.root / "submission.json"

        def submit(role, actor, label, sha=row["image_sha256"]):
            item = {"id": ident, "image_sha256": sha, "annotation": {
                "actor": actor, "kind": "positive", "note": "software fixture",
                "boxes": [{"label": label, "xyxy": [4, 4, 20, 20]}]
            }}
            source.write_text(json.dumps({"queue": role, "rows": [item]}))
            return import_submission(self.destination, source)

        with self.assertRaisesRegex(ValueError, "changed"):
            submit("annotator-a", "author-a", "scratch", "wrong")
        self.assertEqual(submit("annotator-a", "author-a", "scratch"), 1)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            submit("annotator-a", "author-a", "generic_crack")
        with self.assertRaisesRegex(ValueError, "distinct"):
            submit("annotator-b", "AUTHOR-A", "generic_crack")
        self.assertEqual(submit("annotator-b", "human-b", "generic_crack"), 1)
        result = compare(self.destination)
        self.assertTrue(result["distinct_annotator_ids"])
        self.assertEqual(result["counts"], {"disagree": 1, "pending_both": 9})
        self.assertEqual(next(i for i in result["images"] if i["id"] == ident)["box_comparison"][0]["status"], "class")
        for role in ("annotator-a", "annotator-b"):
            _, rows = queue_records(self.destination, role)
            self.assertIsNone(rows[ident]["review"])

    def test_saved_files_can_be_compared_without_import_and_can_report_bad_rows(self):
        for index in range(10):
            register(self.destination, self.image, "fixture", str(index), "fixture", "fixture", "front")
        prepare_practice(self.destination)
        _, records_a = queue_records(self.destination, "annotator-a")
        ident, row = next(iter(records_a.items()))
        left = self.root / "a.json"
        right = self.root / "b.json"

        def item(actor, kind, checksum=row["image_sha256"]):
            return {"id": ident, "image_sha256": checksum, "annotation": {
                "actor": actor, "kind": kind, "boxes": [], "note": "fixture"
            }}

        write_json(left, {"queue": "annotator-a", "rows": [item("left", "clean")]})
        write_json(right, {"queue": "annotator-b", "rows": [item("right", "exclude")]})
        result = compare(self.destination, (left, right))
        self.assertEqual(result["counts"], {"disagree": 1, "pending_both": 9})
        self.assertEqual(len(result["submission_checks"][0]["missing_ids"]), 9)
        self.assertIsNone(queue_records(self.destination, "annotator-a")[1][ident]["annotation"])

        write_json(left, {"queue": "annotator-a", "rows": [item("left", "clean"), item("left", "clean")]})
        check, valid = inspect_submission(self.destination, left)
        self.assertEqual(check["invalid_ids"], [ident])
        self.assertEqual(valid, {})
        self.assertIn("Repeated", check["issues"][0])
        with self.assertRaisesRegex(ValueError, "Expected the annotator-a"):
            compare(self.destination, (right, left))


if __name__ == "__main__":
    unittest.main()
