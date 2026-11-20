"""Regression tests for the hosted gateway. Use the browser smoke for real CPU inference."""

import base64
from http.client import HTTPConnection
import json
from pathlib import Path
import secrets
import sys
from threading import Thread
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.src.supervisor import DemoLimits, MAX_SCAN_BYTES, SupervisorServer, demo_config


class SupervisorGatewayTests(unittest.TestCase):
    def setUp(self):
        self.origin = "https://demo.example.test"
        authorization, parsed_origin = demo_config({
            "REVALUE_DEMO_PASSWORD": secrets.token_urlsafe(24),
            "RENDER_EXTERNAL_URL": self.origin,
        })
        self.auth = authorization.decode("ascii")
        self.server = SupervisorServer(("127.0.0.1", 0), authorization, parsed_origin)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.thread.join, 3)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, payload=None, **headers):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            if payload is not None:
                payload = json.dumps(payload).encode("utf-8")
                headers.setdefault("Content-Type", "application/json")
            connection.request(method, path, payload, headers=headers)
            reply = connection.getresponse()
            return reply.status, dict(reply.getheaders()), reply.read()
        finally:
            connection.close()

    def test_auth_covers_app_api_assets_and_health_is_empty_of_data(self):
        for path in ("/", "/app", "/revalue-design.css", "/decision-support.js", "/catalogue/search?q=iPhone", "/remote-session/test"):
            status, headers, _ = self.request("GET", path)
            self.assertEqual(status, 401, path)
            self.assertIn("Basic", headers["WWW-Authenticate"])
        self.assertEqual(self.request("GET", "/healthz")[2], b"ok\n")
        status, headers, page = self.request("GET", "/", Authorization=self.auth)
        self.assertEqual(status, 200)
        self.assertIn(b"data-supervisor-demo", page)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        for path in ("/scan/test", "/backend/models/revalue_exterior_yolo11n_v0.2.pt", "/model_comparison.js", "/%2e%2e/.env"):
            self.assertEqual(self.request("GET", path, Authorization=self.auth)[0], 404)

    def test_only_same_origin_json_and_small_requests_reach_the_app(self):
        path = "/analyze-exterior"
        self.assertEqual(self.request("POST", path, {}, Authorization=self.auth)[0], 403)
        self.assertEqual(self.request("POST", path, {}, Authorization=self.auth, Origin="https://other.example.test")[0], 403)
        self.assertEqual(self.request("OPTIONS", path, Authorization=self.auth)[0], 405)
        approved = {"Authorization": self.auth, "Origin": self.origin}
        self.assertEqual(self.request("POST", path, **approved, **{"Content-Length": str(MAX_SCAN_BYTES + 1), "Content-Type": "application/json"})[0], 413)
        photo = base64.b64encode(bytes(2 * 1024 * 1024 + 1)).decode("ascii")
        self.assertEqual(self.request("POST", path, {"images": [{"view": "front", "bytes_b64": photo}]}, **approved)[0], 413)
        for disabled in ("/identify-device", "/merge-and-grade", "/remote-session"):
            self.assertEqual(self.request("POST", disabled, {}, **approved)[0], 404)
        self.assertEqual(self.request("POST", "/live-valuation", {"valuation_basis": "manual_grade"}, **approved)[0], 400)

    def test_force_local_inference_and_reject_concurrent_scan(self):
        payload = {"images": [{"view": "front"}, {"view": "back"}], "verify_with_gemini": True}
        approved = {"Authorization": self.auth, "Origin": self.origin}
        with patch("backend.src.server.analyze_exterior", return_value={"status": "ok"}) as analyze:
            self.assertEqual(self.request("POST", "/analyze-exterior", payload, **approved)[0], 200)
            self.assertIs(analyze.call_args.kwargs["run_gemini_verification"], False)
            with self.server.analysis_slot:
                status, headers, _ = self.request("POST", "/analyze-exterior", payload, **approved)
            self.assertEqual(status, 429)
            self.assertEqual(headers["Retry-After"], "5")
            self.assertEqual(analyze.call_count, 1)

    def test_rate_limit_blocks_failed_logins_separately(self):
        self.server.limits = DemoLimits({"auth_failure": 1, "read": 1, "write": 1, "analysis": 1})
        self.assertEqual(self.request("GET", "/", Authorization="Basic invalid")[0], 401)
        self.assertEqual(self.request("GET", "/", Authorization="Basic invalid")[0], 429)
        self.assertEqual(self.request("GET", "/", Authorization=self.auth)[0], 200)
        self.assertEqual(self.request("GET", "/", Authorization=self.auth)[0], 429)
        self.assertEqual(self.request("HEAD", "/healthz")[0], 200)

    def test_fail_closed_config_and_sliding_window(self):
        with self.assertRaises(ValueError):
            demo_config({})
        with self.assertRaises(ValueError):
            demo_config({"REVALUE_DEMO_PASSWORD": secrets.token_urlsafe(24), "REVALUE_PUBLIC_ORIGIN": "http://demo.example.test"})
        now = [20]
        limits = DemoLimits({"analysis": 1}, clock=lambda: now[0])
        self.assertTrue(limits.allow("analysis"))
        self.assertFalse(limits.allow("analysis"))
        now[0] = 80
        self.assertTrue(limits.allow("analysis"))


if __name__ == "__main__":
    unittest.main()
