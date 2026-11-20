"""Protected, single-instance demonstration gateway for the existing ReValue app."""

from __future__ import annotations

from base64 import b64encode
from collections import deque
from hashlib import file_digest
from hmac import compare_digest
from http.server import ThreadingHTTPServer
import json
import os
import re
import sys
from threading import BoundedSemaphore, Lock
from time import monotonic
from urllib.parse import urlsplit

from .server import APP_HTML, ReValueHandler, _json_response, _text_response
from .yolo_detector import DEFAULT_MODEL_PATH, load_yolo_model

MAX_PHOTO_BYTES = 2 * 1024 * 1024
MAX_SCAN_BYTES = 14 * 1024 * 1024
MAX_FORM_BYTES = 16 * 1024
EXPECTED_MODEL_SHA256 = "b26c49987eb44ab60ba0368420b5aa6fa89462b72212d5a83773aabc9a1d543f"
POST_ROUTES = {"/confirm-device", "/analyze-exterior", "/live-valuation"}
READ_ROUTES = {
    "/", "/app", "/catalogue/search", "/decision-support.js", "/revalue-design.css", "/revalue-professional.css", "/revalue-legacy.css",
    "/revalue-phone-studio.jpg", "/iphone13pro_back_damage.jpg", "/samsung_s23_ultra_back_damage.jpg",
    "/shop_ecophone.jpg", "/shop_fastfix.jpg", "/shop_greentech.jpg", "/shop_kl_mobile_repair.jpg", "/shop_valuemax.jpg",
}
PER_MINUTE = {"auth_failure": 30, "read": 240, "write": 40, "analysis": 6}


def demo_config(environ):
    password = environ.get("REVALUE_DEMO_PASSWORD", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", password):
        raise ValueError("Set REVALUE_DEMO_PASSWORD to a random URL-safe password of 24–128 characters.")
    raw_origin = environ.get("REVALUE_PUBLIC_ORIGIN") or environ.get("RENDER_EXTERNAL_URL", "")
    origin = urlsplit(raw_origin)
    if (origin.scheme != "https" or not origin.hostname or origin.username is not None or origin.password is not None
            or origin.path not in ("", "/") or origin.query or origin.fragment
            or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]{1,5})?", origin.netloc)):
        raise ValueError("Set REVALUE_PUBLIC_ORIGIN to the exact public HTTPS origin if it is not provided by Render.")
    authorization = b"Basic " + b64encode(f"supervisor:{password}".encode("ascii"))
    return authorization, f"https://{origin.netloc.lower()}"


class DemoLimits:
    def __init__(self, limits=None, clock=monotonic):
        self.limits = PER_MINUTE if limits is None else limits
        self.clock = clock
        self.events = {bucket: deque() for bucket in self.limits}
        self.lock = Lock()

    def allow(self, bucket):
        with self.lock:
            now = self.clock()
            events = self.events[bucket]
            while events and events[0] <= now - 60:
                events.popleft()
            if len(events) >= self.limits[bucket]:
                return False
            events.append(now)
            return True


class SupervisorHandler(ReValueHandler):
    allow_external_photo_verification = False
    server_version = "ReValue-Supervisor"
    sys_version = ""

    def setup(self):
        self.request.settimeout(15)
        super().setup()

    def log_message(self, *args):
        # Routes, queries, credentials and client identifiers stay out of application logs.
        pass

    def send_header(self, keyword, value):
        if not keyword.lower().startswith("access-control-"):
            super().send_header(keyword, value)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        self.send_header("Strict-Transport-Security", "max-age=86400")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; object-src 'none'; "
                         "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        super().end_headers()

    def _reply(self, status, message, *, challenge=False, retry=None):
        self.close_connection = True
        api = self.command == "POST" or self.path.startswith("/catalogue/")
        raw = (json.dumps({"status": "error", "error": message}) if api else message).encode("utf-8")
        self.send_response(status)
        if challenge:
            self.send_header("WWW-Authenticate", 'Basic realm="ReValue Supervisor Demo", charset="UTF-8"')
        if retry is not None:
            self.send_header("Retry-After", str(retry))
        self.send_header("Content-Type", "application/json" if api else "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _authenticated(self):
        authorization = self.headers.get_all("Authorization", [])
        if len(authorization) == 1 and compare_digest(authorization[0].encode("latin-1"), self.server.authorization):
            return True
        if self.server.limits.allow("auth_failure"):
            self._reply(401, "Supervisor credentials required.", challenge=True)
        else:
            self._reply(429, "Too many login attempts. Try again in a minute.", retry=60)
        return False

    def _read_route(self):
        if self.path == "/healthz":
            self._reply(200, "ok\n")
            return
        if not self._authenticated():
            return
        path = urlsplit(self.path).path
        if path not in READ_ROUTES and not re.fullmatch(r"/catalogue/device/phone_[a-f0-9]{16}", path):
            self._reply(404, "Page unavailable in this demo.")
            return
        if not self.server.limits.allow("read"):
            self._reply(429, "Too many requests. Try again in a minute.", retry=60)
            return
        if self.command == "HEAD":
            self._reply(200, "")
        elif path in {"/", "/app"}:
            _text_response(self, 200, self.server.page)
        else:
            super().do_GET()

    do_GET = do_HEAD = _read_route

    def do_OPTIONS(self):
        if self._authenticated():
            self._reply(405, "Use the demo from its HTTPS page.")

    def do_POST(self):
        if not self._authenticated():
            return
        if self.path not in POST_ROUTES:
            self._reply(404, "Action unavailable in this demo.")
            return
        if self.headers.get_all("Origin", []) != [self.server.origin] or self.headers.get_content_type() != "application/json":
            self._reply(403, "Submit from the demo’s HTTPS page using JSON.")
            return
        scan = self.path == "/analyze-exterior"
        lengths = self.headers.get_all("Content-Length", [])
        if (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", lengths[0]) or self.headers.get("Transfer-Encoding")
                or int(lengths[0]) == 0):
            self._reply(400, "Send a complete request with a valid Content-Length.")
            return
        if int(lengths[0]) > (MAX_SCAN_BYTES if scan else MAX_FORM_BYTES):
            self._reply(413, "Upload exceeds the demo limit.")
            return
        if not self.server.limits.allow("analysis" if scan else "write"):
            self._reply(429, "Too many requests. Try again in a minute.", retry=60)
            return
        if not scan:
            self._dispatch()
        elif not self.server.analysis_slot.acquire(blocking=False):
            self._reply(429, "Another analysis is running. Try again shortly.", retry=5)
        else:
            try:
                self._dispatch()
            finally:
                self.server.analysis_slot.release()

    def _dispatch(self):
        try:
            super().do_POST()
        except TimeoutError:
            self.close_connection = True

    def _read_json(self):
        payload = super()._read_json()
        if self.path == "/analyze-exterior" and isinstance(payload.get("images"), list):
            for item in payload["images"]:
                data = item.get("bytes_b64") if isinstance(item, dict) else None
                if isinstance(data, str):
                    if len(data) > 4 * ((MAX_PHOTO_BYTES + 2) // 3):
                        raise OverflowError
                    padding = 2 if data.endswith("==") else int(data.endswith("="))
                    if len(data) * 3 // 4 - padding > MAX_PHOTO_BYTES:
                        raise OverflowError
        if self.path == "/live-valuation" and payload.get("valuation_basis") != "exterior_scan":
            raise ValueError("The demo requires a completed scan for valuation.")
        return payload


class SupervisorServer(ThreadingHTTPServer):
    request_queue_size = 16

    def __init__(self, address, authorization, origin, limits=None):
        self.authorization = authorization
        self.origin = origin
        self.limits = limits if limits is not None else DemoLimits()
        self.analysis_slot = BoundedSemaphore(1)
        self.connections = BoundedSemaphore(16)
        self.page = APP_HTML.read_text(encoding="utf-8").replace('<html lang="en">', '<html lang="en" data-supervisor-demo>', 1)
        super().__init__(address, SupervisorHandler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()

    def handle_error(self, request, client_address):
        print("Supervisor request could not complete.", file=sys.stderr)


def run():
    authorization, origin = demo_config(os.environ)
    # These optional integrations belong to the local application rather than this hosted demo.
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "REVALUE_AUDITED_MARKET_CSV", "REVALUE_DETECTOR_WEIGHTS", "REVALUE_DETECTOR_IMGSZ"):
        os.environ.pop(name, None)
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    os.environ.setdefault("MKL_NUM_THREADS", "2")

    import cv2
    import torch
    from ultralytics import settings

    torch.set_num_threads(2)
    cv2.setNumThreads(2)
    settings.update({"sync": False})
    with DEFAULT_MODEL_PATH.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != EXPECTED_MODEL_SHA256:
            raise ValueError("The bundled YOLO11n checkpoint failed SHA-256 verification.")
    load_yolo_model()
    with SupervisorServer(("0.0.0.0", int(os.environ.get("PORT", "7860"))), authorization, origin) as server:
        print("Supervisor demo ready. HTTPS is terminated by the configured host.", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    try:
        run()
    except ValueError as error:
        raise SystemExit(str(error)) from None
