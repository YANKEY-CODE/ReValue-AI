"""HTTP regressions for guided exterior scans and remote capture."""

from __future__ import annotations

import base64
import json
import os
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.src.exterior_analysis import analyze_exterior
from backend.src.exterior_verification import verify_damage_with_gemini
from backend.src.gemini_client import GeminiTemporaryUnavailable
from backend.src.schemas import GeminiDamageVerification, ImageInput, YoloDetection
from backend.src.server import REMOTE_SESSIONS, REMOTE_VIEWS, ReValueHandler
from backend.src.yolo_detector import YoloDetectorUnavailable


def photo(view):
    data = BytesIO()
    Image.new("RGB", (64, 64), "white").save(data, format="PNG")
    return {"view": view, "mime_type": "image/png", "bytes_b64": base64.b64encode(data.getvalue()).decode()}


class ExteriorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), ReValueHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        REMOTE_SESSIONS.clear()

    def request(self, path, data=None):
        body = data if isinstance(data, bytes) else json.dumps(data).encode() if data is not None else None
        url = f"http://127.0.0.1:{self.server.server_port}{path}"
        try:
            response = urlopen(Request(url, data=body), timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_invalid_bodies_and_photos_cannot_produce_a_grade(self):
        for body in (b"{", [], {"images": "bad"}, {"images": [photo("front")]},
                     {"images": [photo("front"), photo("back") | {"bytes_b64": "bm90IGEgcGhvdG8="}]}):
            with self.subTest(body_type=type(body)):
                status, result = self.request("/analyze-exterior", body)
                self.assertEqual(status, 400)
                self.assertEqual(result.get("grade", {}).get("exterior_grade", "pending"), "pending")

    def test_model_failure_leaves_grade_pending(self):
        with patch("backend.src.exterior_analysis.detect_exterior_damage", side_effect=YoloDetectorUnavailable("load failed")):
            status, result = self.request("/analyze-exterior", {"images": [photo("front"), photo("back")]})
        self.assertEqual((status, result["grade"]["exterior_grade"]), (503, "pending"))

    def test_uncorroborated_and_disputed_predictions_are_distinct(self):
        images = [ImageInput(**photo(view)) for view in REMOTE_VIEWS]
        candidate = YoloDetection("screen_crack", 0.8, "front", "generic_crack")
        result = analyze_exterior(images, detector=lambda _: [candidate], run_gemini_verification=False)
        self.assertEqual((result["grade"]["exterior_grade"], result["assessment_basis"]), ("C", "provisional"))
        for status, grade, basis in [("supports", "C", "ai_corroborated"), ("uncertain", "pending", "review_required")]:
            verification = GeminiDamageVerification("screen_crack", "front", status)
            with patch("backend.src.exterior_analysis.verify_damage_with_gemini", return_value=("ok", [verification])):
                result = analyze_exterior(images, detector=lambda _: [candidate])
            self.assertEqual((result["grade"]["exterior_grade"], result["assessment_basis"]), (grade, basis))
        side_crack = YoloDetection(None, 0.7, "right_side", "generic_crack", requires_gemini_resolution=True)
        result = analyze_exterior(images, detector=lambda _: [side_crack], run_gemini_verification=False)
        self.assertEqual(result["grade"]["exterior_grade"], "pending")

    def test_optional_verifier_outage_is_reported(self):
        class UnavailableClient:
            def generate_structured(self, **kwargs):
                raise GeminiTemporaryUnavailable("fallback")

        self.assertEqual(
            verify_damage_with_gemini(images=[], yolo_detections=[], client=UnavailableClient()),
            ("temporarily_unavailable", []),
        )

    def test_remote_upload_needs_valid_photos_and_explicit_completion(self):
        _, session = self.request("/remote-session", {})
        path = f"/remote-session/{session['session_id']}"
        self.assertEqual(self.request(path + "/photo", photo("front") | {"bytes_b64": "!!!"})[0], 400)
        self.assertEqual(self.request(path + "/complete", {})[0], 400)
        for view in REMOTE_VIEWS:
            status, response = self.request(path + "/photo", photo(view))
            self.assertEqual(status, 200)
            self.assertFalse(response["complete"])
            self.assertNotIn("bytes_b64", response["views"][view])
        self.assertTrue(self.request(path + "/complete", {})[1]["complete"])
        response = self.request(path)[1]
        self.assertEqual(response["received_count"], 5)
        self.assertTrue(response["views"]["right_side"]["bytes_b64"])
        self.assertEqual(self.request(path + "/photo", photo("front"))[0], 409)

    @unittest.skipUnless(os.environ.get("REVALUE_TEST_REAL_MODEL") == "1", "opt-in CPU inference check")
    def test_bundled_model_processes_five_guided_photos(self):
        with patch("backend.src.exterior_analysis.verify_damage_with_gemini", return_value=("not_configured", [])):
            status, response = self.request("/analyze-exterior", {"images": [photo(view) for view in REMOTE_VIEWS]})
        self.assertEqual((status, response["assessment_basis"]), (200, "provisional"))
        self.assertEqual(response["detections"], [])
        self.assertEqual(response["grade"]["exterior_grade"], "A")


if __name__ == "__main__":
    unittest.main()
