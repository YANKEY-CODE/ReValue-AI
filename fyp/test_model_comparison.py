"""Regression tests for a qualitative comparison, with optional real CPU inference."""

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from . import model_comparison as comparison
from .benchmark.checkpoints import HOUDAN_NAMES, load_houdan


def image_bytes():
    photo = Image.new("RGB", (64, 48), "red")
    photo.paste((0, 0, 255), (0, 0, 32, 48))
    exif = photo.getexif()
    exif[274] = 6  # Upright dimensions become 48 x 64.
    buffer = BytesIO()
    photo.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


class ComparisonTests(unittest.TestCase):
    def test_uses_identical_upright_inputs_settings_and_comparison_only_labels(self):
        calls = []

        def model(key, names, rows):
            def predict(frame, **settings):
                calls.append((key, frame.copy(), settings))
                frame[:] = 0  # A model mutating its input cannot affect the other model.
                return [SimpleNamespace(names=names, boxes=SimpleNamespace(data=np.array(rows)), speed={"inference": 1.0})]
            return SimpleNamespace(predict=predict)

        runner = comparison.ComparisonRunner({
            "revalue": model("revalue", {0: "generic_crack", 1: "scratch"}, []),
            "houdan": model("houdan", HOUDAN_NAMES, [[5, 6, 20, 30, .8, i] for i in (0, 1, 2, 3)]),
        }, {})
        result = runner.compare(image_bytes())
        runner.compare(image_bytes())
        self.assertEqual([key for key, _, _ in calls], ["revalue", "houdan", "revalue", "houdan", "houdan", "revalue"])
        for _, frame, settings in calls:
            np.testing.assert_array_equal(frame, calls[0][1])
            self.assertEqual(frame.shape, (64, 48, 3))
            self.assertEqual((settings["imgsz"], settings["conf"], settings["device"], settings["rect"]), (640, .25, "cpu", False))
        self.assertEqual(result["image"]["width"], 48)
        self.assertEqual(result["models"]["revalue"]["counts"], {"generic_crack": 0, "scratch": 0})
        houdan = result["models"]["houdan"]
        self.assertEqual(houdan["counts"], {"generic_crack": 1, "scratch": 1, "bump": 1, "paint": 1})
        self.assertEqual(houdan["detections"][-1]["raw_class"], "crack")
        self.assertEqual(houdan["detections"][-1]["comparison_class"], "generic_crack")

    def test_wrong_release_bytes_fail_before_torch_load(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "best.pt"
            with path.open("wb") as stream:
                stream.truncate(comparison.HOUDAN_BYTES)
            torch, yolo = Mock(), Mock()
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                load_houdan(path, yolo, torch)
            torch.load.assert_not_called()
            yolo.assert_not_called()

    def test_bad_download_is_never_cached_and_repo_path_is_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            comparison.houdan_checkpoint(comparison.ROOT / "best.pt")
        with TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            with patch.object(comparison, "urlopen", return_value=BytesIO(b"invalid download")) as fetch:
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    comparison.houdan_checkpoint()
                self.assertEqual(fetch.call_args.args[0], comparison.HOUDAN_URL)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_http_rejects_cross_origin_oversized_and_corrupt_images(self):
        runner = comparison.ComparisonRunner({}, {})
        with ThreadingHTTPServer((comparison.HOST, 0), comparison.ComparisonHandler) as server:
            server.runner = runner
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()

            def request(method, path, body=None, **headers):
                with_http = HTTPConnection(comparison.HOST, server.server_port, timeout=5)
                try:
                    with_http.request(method, path, body, headers=headers)
                    response = with_http.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    with_http.close()

            try:
                self.assertEqual(request("GET", "/metadata")[1]["comparison_type"], "qualitative")
                binary = {"Content-Type": "application/octet-stream"}
                self.assertEqual(request("POST", "/compare", b"invalid", Origin="https://example.invalid", **binary)[0], 403)
                self.assertEqual(request("POST", "/compare", b"invalid", Host="example.invalid", **binary)[0], 403)
                self.assertEqual(request("POST", "/compare", b"invalid")[0], 415)
                self.assertEqual(request("POST", "/compare", **{"Content-Length": str(comparison.MAX_IMAGE_BYTES + 1)}, **binary)[0], 413)
                self.assertEqual(request("POST", "/compare", b"invalid", **binary)[0], 400)
            finally:
                server.shutdown()
                worker.join()

    @unittest.skipUnless(os.environ.get("REVALUE_HOUDAN_TEST_WEIGHTS"), "external verified Houdan weights required")
    def test_both_real_models_report_cpu_times(self):
        path = comparison.houdan_checkpoint(Path(os.environ["REVALUE_HOUDAN_TEST_WEIGHTS"]))
        runner = comparison.load_runner(path)
        report = runner.compare(image_bytes())
        self.assertEqual(set(report["models"]), {"revalue", "houdan"})
        for model in report["models"].values():
            self.assertGreater(model["cpu_inference_ms"], 0)
            self.assertGreaterEqual(model["cpu_predict_wall_ms"], model["cpu_inference_ms"])


if __name__ == "__main__":
    unittest.main()
