"""Synthetic checks for the private SSGD ZIP intake."""

from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from PIL import Image, ImageDraw

from prepare_ssgd import extract_archive, prepare


class SSGDIntakeTests(unittest.TestCase):
    def test_archive_uses_one_fold_and_keeps_invalid_and_duplicate_assets_unapproved(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "official-layout-fixture.zip"
            folder = "defect_screen"
            png = BytesIO()
            image = Image.new("RGB", (80, 64), "white")
            ImageDraw.Draw(image).line((16, 8, 40, 32), fill="black", width=3)
            image.save(png, format="PNG")
            categories = [{"id": 1, "name": "crack"}, {"id": 2, "name": "scratch"},
                          {"id": 3, "name": "oil"}]
            with ZipFile(archive, "w") as bundle:
                for name in ("crack.png", "duplicate.png"):
                    bundle.writestr(f"{folder}/images_lb101/{name}", png.getvalue())
                bundle.writestr(f"{folder}/images_lb101/corrupt.png", b"corrupt image")
                for split, names in (("train", ["crack.png", "corrupt.png"]), ("val", ["duplicate.png"])):
                    dataset = {
                        "images": [{"id": i, "file_name": name, "width": 80, "height": 64}
                                   for i, name in enumerate(names)],
                        "categories": categories,
                        "annotations": [{"id": i, "image_id": 0, "category_id": i + 1,
                                         "bbox": [10 + i, 10, 12, 12]} for i in range(len(categories))],
                    }
                    for fold in (1, 2):
                        bundle.writestr(f"{folder}/annotations/lb101/{split}{fold}.json", json.dumps(dataset))
            work = root / "intake"
            work.mkdir()
            report = prepare(archive, work, "generated software fixture")
            self.assertEqual(report["unique_cohort_image_files"], 3)
            self.assertEqual(report["unique_fold1_annotation_image_paths"], 3)
            self.assertEqual(report["raw_fold1_annotation_rows"], 6)
            self.assertEqual(report["proposed_boxes_by_class"], {"generic_crack": 2, "scratch": 2})
            self.assertEqual(report["approved_images"], 0)
            self.assertEqual(report["duplicate_candidates"], 1)
            self.assertTrue(report["intake"][0]["issues"])
            candidates = (work / "pool" / "source_references").glob("*.json")
            self.assertEqual(len(list(candidates)), 2)
            self.assertFalse((work / "pool" / "labels").exists())

    def test_unsafe_members_are_rejected_before_extraction(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "fixture.zip"
            for names in (["../outside.png"], ["A.png", "a.png"], ["images/COM1.png"]):
                with self.subTest(names=names):
                    with ZipFile(archive, "w") as bundle:
                        for name in names:
                            bundle.writestr(name, b"fixture")
                    with self.assertRaisesRegex(ValueError, "ZIP member"):
                        extract_archive(archive, root / "extracted")
                    self.assertFalse((root / "extracted").exists())


if __name__ == "__main__":
    unittest.main()
