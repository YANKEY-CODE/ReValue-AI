from __future__ import annotations

import json
import os
import secrets
import sys
import time
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .assessment_receipt import PRICEABLE_BASES, issue_receipt, verify_receipt
from .device_identification import identify_device
from .exterior_analysis import analyze_exterior
from .grading_rules import grade_from_atomic_damage
from .image_upload import EXTERIOR_VIEWS, decode_image
from .live_estimate import build_live_estimate
from .market_evidence import canonicalize_confirmed_device, exterior_grade_error_response, normalize_exterior_grade, retrieve_current_market_evidence
from .phone_catalogue import confirm_device, get_catalogue_device, search_catalogue
from .schemas import ImageInput, MergedDamage, YoloDetection

APP_DIR = Path(__file__).resolve().parents[2] / "app"
APP_HTML = APP_DIR / "ReValue-AI-Prototype-v1.16.1-predeployment-preview.html"
VENDOR_DIR = Path(__file__).resolve().parents[1] / "vendor"
MAX_JSON_BYTES = 56 * 1024 * 1024
SESSION_TTL_SECONDS = 60 * 60
REMOTE_VIEWS = ["front", "back", "camera", "left_side", "right_side"]
REMOTE_VIEW_LABELS = {
    "front": "Front",
    "back": "Back",
    "camera": "Camera Close-up",
    "left_side": "Left Side",
    "right_side": "Right Side",
}
REMOTE_SESSIONS: dict[str, dict[str, Any]] = {}


def _uploaded_images(payload: dict[str, Any]) -> list[ImageInput]:
    items = payload.get("images")
    if not isinstance(items, list) or not 1 <= len(items) <= 5:
        raise ValueError("Expected one to five labelled exterior images.")
    try:
        images = [ImageInput(**item) for item in items]
    except TypeError as exc:
        raise ValueError("Each image must contain a view and optional image fields.") from exc
    if any(
        not isinstance(image.view, str) or image.view not in EXTERIOR_VIEWS
        or any(value is not None and not isinstance(value, str)
               for value in (image.filename, image.mime_type, image.bytes_b64))
        for image in images
    ):
        raise ValueError("Use an exterior view label and text image fields.")
    return images


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _text_response(handler: BaseHTTPRequestHandler, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
    raw = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)


def _file_response(handler: BaseHTTPRequestHandler, path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    content_types = {
        ".html": "text/html; charset=utf-8",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
        ".css": "text/css; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
    }
    raw = path.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", content_types.get(path.suffix.lower(), "application/octet-stream"))
    handler.send_header("Content-Length", str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)
    return True


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [token for token, session in REMOTE_SESSIONS.items() if session["expires_at_epoch"] < now]
    for token in expired:
        REMOTE_SESSIONS.pop(token, None)


def _new_session(origin: str) -> dict[str, Any]:
    _cleanup_sessions()
    token = f"RVA-LIVE-{secrets.token_urlsafe(18)}"
    now = time.time()
    session = {
        "session_id": token,
        "created_at_epoch": now,
        "expires_at_epoch": now + SESSION_TTL_SECONDS,
        "status": "open",
        "views": {view: {"view": view, "label": REMOTE_VIEW_LABELS[view], "status": "empty"} for view in REMOTE_VIEWS},
        "session_url": f"{origin.rstrip('/')}/scan/{quote(token)}",
        "completed_at_epoch": None,
    }
    REMOTE_SESSIONS[token] = session
    return _public_session(session, include_images=False)


def _public_session(session: dict[str, Any], *, include_images: bool = True) -> dict[str, Any]:
    views: dict[str, Any] = {}
    for view, item in session["views"].items():
        public_item = {key: value for key, value in item.items() if include_images or key not in {"bytes_b64"}}
        views[view] = public_item
    received = sum(1 for item in session["views"].values() if item.get("status") == "complete")
    return {
        "status": session["status"],
        "session_id": session["session_id"],
        "session_url": session["session_url"],
        "expires_at_epoch": session["expires_at_epoch"],
        "received_count": received,
        "required_count": len(REMOTE_VIEWS),
        "complete": received == len(REMOTE_VIEWS) and session["status"] == "complete",
        "views": views,
    }


def _session_or_error(token: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    _cleanup_sessions()
    session = REMOTE_SESSIONS.get(token)
    if not session:
        return None, {"status": "error", "error": "scan_session_not_found_or_expired"}
    if session.get("status") == "expired":
        return None, {"status": "error", "error": "scan_session_expired"}
    return session, None


def _qr_svg(url: str) -> tuple[int, str, str]:
    try:
        if VENDOR_DIR.exists() and str(VENDOR_DIR) not in sys.path:
            sys.path.insert(0, str(VENDOR_DIR))
        import qrcode
        import qrcode.image.svg
    except Exception:
        safe = json.dumps(url)
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="240" height="240" viewBox="0 0 240 240" role="img" aria-label="QR dependency missing">
<rect width="240" height="240" rx="16" fill="#eafffb"/>
<text x="120" y="102" text-anchor="middle" font-family="Arial" font-size="13" font-weight="700" fill="#09252b">QR library required</text>
<text x="120" y="126" text-anchor="middle" font-family="Arial" font-size="10" fill="#1f4a52">Copy Link works now</text>
<script type="application/json" id="qr-target">{safe}</script>
</svg>"""
        return 503, svg, "image/svg+xml"

    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage)
    return 200, image.to_string(encoding="unicode"), "image/svg+xml"


def _remote_capture_page(token: str) -> str:
    labels = json.dumps(REMOTE_VIEW_LABELS)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f6f8f5">
<title>ReValue AI | Remote exterior capture</title>
<link rel="stylesheet" href="/revalue-design.css">
<link rel="stylesheet" href="/revalue-remote.css">
</head>
<body>
<div class="wrap">
  <div class="rv-brand"><span class="rv-mark" aria-hidden="true">RV</span>ReValue AI</div>
  <div class="rv-eyebrow">Remote camera</div>
  <h1>Exterior Scan</h1>
  <section class="rv-card card" id="captureCard">
    <div class="stage" id="stage" role="status">1 of 5 · Front</div>
    <div class="progress" id="progress" aria-hidden="true"></div>
    <div class="camera" id="cameraBox"><div class="hint">Use the camera or upload a clear photo.</div><div class="guide"></div></div>
    <input id="fileInput" type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" capture="environment" hidden>
    <button class="rv-button" type="button" onclick="openCamera()">Take Photo</button>
    <div class="row" id="previewActions" style="display:none"><button class="rv-button-secondary" type="button" onclick="retake()">Retake</button><button class="rv-button" type="button" onclick="usePhoto()">Use Photo</button></div>
    <button class="rv-button" id="sendBtn" type="button" onclick="sendPhotos()" style="display:none">Send Photos</button>
    <p class="rv-alert" id="captureError" role="alert" hidden></p>
  </section>
  <section class="rv-card card doneText" id="doneText" role="status">Photos sent successfully<span>You can return to the other device.</span></section>
</div>
<script>
const SESSION_ID={json.dumps(token)};
const VIEWS={json.dumps(REMOTE_VIEWS)};
const LABELS={labels};
let current=0, pending=null;
function render(){{document.getElementById('stage').textContent=current<VIEWS.length?`${{current+1}} of ${{VIEWS.length}} · ${{LABELS[VIEWS[current]]}}`:'All five views ready';document.getElementById('progress').innerHTML=VIEWS.map((v,i)=>`<i class="dot ${{i<current?'done':i===current?'current':''}}"></i>`).join('');document.getElementById('sendBtn').style.display=current>=VIEWS.length?'block':'none'}}
function openCamera(){{if(posting||current>=VIEWS.length)return;document.getElementById('fileInput').click()}}
document.getElementById('fileInput').addEventListener('change',e=>{{const file=e.target.files&&e.target.files[0];if(!file)return;const reader=new FileReader();reader.onload=()=>{{pending={{name:file.name,type:file.type||'image/jpeg',data:String(reader.result)}};document.getElementById('cameraBox').innerHTML=`<img src="${{pending.data}}" alt="Preview"><div class="guide"></div>`;document.getElementById('previewActions').style.display='grid'}};reader.onerror=()=>alert('Could not read the image. Please try another photo.');reader.readAsDataURL(file)}});
function retake(){{pending=null;document.getElementById('previewActions').style.display='none';document.getElementById('cameraBox').innerHTML='<div class="hint">Use the camera or upload a clear photo.</div><div class="guide"></div>';document.getElementById('fileInput').value=''}}
let posting=false;
const captureError=document.getElementById("captureError");
function showCaptureError(message){{captureError.textContent=message;captureError.hidden=!message}}
async function postCapture(path, payload){{
  const response=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(payload)}});
  const result=await response.json();
  if(!response.ok)throw new Error(result.error||'Upload failed. Please try again.');
}}
async function usePhoto(){{
  if(!pending||posting||current>=VIEWS.length)return;
  posting=true;
  showCaptureError('');
  try{{
    await postCapture(`/remote-session/${{encodeURIComponent(SESSION_ID)}}/photo`,{{
      view:VIEWS[current],filename:pending.name,mime_type:pending.type,bytes_b64:pending.data.split(',')[1]||''
    }});
    current++;
    retake();
    render();
  }}catch(error){{showCaptureError(error.message)}}finally{{posting=false}}
}}
async function sendPhotos(){{
  if(posting||current<VIEWS.length)return;
  posting=true;
  showCaptureError('');
  try{{
    await postCapture(`/remote-session/${{encodeURIComponent(SESSION_ID)}}/complete`,{{}});
    document.getElementById('captureCard').style.display='none';
    document.getElementById('doneText').style.display='block';
  }}catch(error){{showCaptureError(error.message)}}finally{{posting=false}}
}}
render();
</script>
</body>
</html>"""


class ReValueHandler(BaseHTTPRequestHandler):
    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0:
            raise ValueError("Invalid Content-Length")
        if length > MAX_JSON_BYTES:
            raise OverflowError("Request exceeds upload limit")
        if not length:
            return {}
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        return payload

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    def do_HEAD(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/app"}:
            if _file_response(self, APP_HTML):
                return
            fallback = APP_DIR / "ReValue-AI-Prototype-v1.15.0-live-exterior-preview.html"
            if _file_response(self, fallback):
                return
        if path.startswith("/scan/"):
            token = unquote(path.rsplit("/", 1)[-1])
            session, error = _session_or_error(token)
            if error:
                _text_response(self, 404, "<h1>Scan session expired</h1><p>Please create a new ReValue scan session.</p>")
                return
            _text_response(self, 200, _remote_capture_page(session["session_id"]))
            return
        if path.startswith("/remote-session/") and path.endswith("/qr.svg"):
            token = unquote(path.split("/")[2])
            session, error = _session_or_error(token)
            if error:
                _json_response(self, 404, error)
                return
            status, svg, content_type = _qr_svg(session["session_url"])
            _text_response(self, status, svg, content_type)
            return
        if path.startswith("/remote-session/"):
            token = unquote(path.rsplit("/", 1)[-1])
            session, error = _session_or_error(token)
            _json_response(self, 404 if error else 200, error or _public_session(session))
            return
        asset = APP_DIR / unquote(path.lstrip("/"))
        try:
            asset.resolve().relative_to(APP_DIR.resolve())
        except Exception:
            asset = Path()
        if asset and _file_response(self, asset):
            return
        if self.path == "/health":
            _json_response(self, 200, {"status": "ok", "service": "revalue-phase6a3-backend"})
            return
        if self.path == "/market-evidence/status":
            _json_response(self, 200, retrieve_current_market_evidence())
            return
        if path == "/catalogue/search":
            query = parse_qs(parsed.query).get("q", [""])[0]
            _json_response(self, 200, {"results": search_catalogue(query)})
            return
        if path.startswith("/catalogue/device/"):
            catalogue_id = unquote(path.rsplit("/", 1)[-1])
            device = get_catalogue_device(catalogue_id)
            _json_response(self, 200 if device else 404, {"device": device} if device else {"error": "not_found"})
            return
        _json_response(self, 404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        try:
            payload = self._read_json()
        except OverflowError:
            self.close_connection = True
            _json_response(self, 413, {"status": "error", "error": "Request exceeds upload limit."})
            return
        except ValueError:
            _json_response(self, 400, {"status": "error", "error": "Expected a valid JSON object."})
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/remote-session":
            origin = self.headers.get("Origin") or f"http://{self.headers.get('Host', '127.0.0.1:8765')}"
            _json_response(self, 200, _new_session(origin))
            return
        if path.startswith("/remote-session/") and path.endswith("/photo"):
            token = unquote(path.split("/")[2])
            session, error = _session_or_error(token)
            if error:
                _json_response(self, 404, error)
                return
            if session["status"] not in {"open", "ready"}:
                _json_response(self, 409, {"status": "error", "error": "scan_session_closed"})
                return
            view = payload.get("view")
            if view not in REMOTE_VIEWS:
                _json_response(self, 400, {"status": "error", "error": "valid_view_required"})
                return
            try:
                image = ImageInput(view=view, mime_type=payload.get("mime_type") or "image/jpeg", bytes_b64=payload.get("bytes_b64"))
                decode_image(image).close()
            except ValueError as exc:
                _json_response(self, 400, {"status": "error", "error": str(exc)})
                return
            except ImportError:
                _json_response(self, 503, {"status": "error", "error": "Image dependencies unavailable."})
                return
            session["views"][view] = {
                "view": view,
                "label": REMOTE_VIEW_LABELS[view],
                "status": "complete",
                "filename": payload.get("filename") or f"{view}.jpg",
                "mime_type": payload.get("mime_type") or "image/jpeg",
                "bytes_b64": payload["bytes_b64"],
                "uploaded_at_epoch": time.time(),
            }
            if all(item.get("status") == "complete" for item in session["views"].values()):
                session["status"] = "ready"
            _json_response(self, 200, _public_session(session, include_images=False))
            return
        if path.startswith("/remote-session/") and path.endswith("/complete"):
            token = unquote(path.split("/")[2])
            session, error = _session_or_error(token)
            if error:
                _json_response(self, 404, error)
                return
            if not all(item.get("status") == "complete" for item in session["views"].values()):
                _json_response(self, 400, {"status": "error", "error": "all_five_views_required"})
                return
            session["status"] = "complete"
            session["completed_at_epoch"] = time.time()
            _json_response(self, 200, _public_session(session, include_images=False))
            return
        if self.path == "/identify-device":
            try:
                images = _uploaded_images(payload)
                for image in images:
                    if image.bytes_b64 is not None:
                        decode_image(image).close()
            except ValueError as exc:
                _json_response(self, 400, {"status": "error", "error": str(exc)})
                return
            _json_response(self, 200, asdict(identify_device(images)))
            return

        if self.path == "/confirm-device":
            _json_response(
                self,
                200,
                confirm_device(
                    catalogue_id=payload.get("catalogue_id", ""),
                    storage=payload.get("storage"),
                ),
            )
            return

        if self.path == "/analyze-exterior":
            try:
                images = _uploaded_images(payload)
            except ValueError as exc:
                _json_response(self, 400, {"status": "error", "error": str(exc)})
                return
            device = None
            if "confirmed_device" in payload:
                ok, error, device = canonicalize_confirmed_device(payload["confirmed_device"])
                if not ok:
                    _json_response(self, 400, {"status": "error", "error": error})
                    return
            result = analyze_exterior(images, run_gemini_verification=payload.get("verify_with_gemini", True) is True)
            if device and result["status"] == "ok" and result["assessment_basis"] in PRICEABLE_BASES:
                result["assessment_receipt"] = issue_receipt(device, result["grade"]["exterior_grade"], result["assessment_basis"])
            status = {"error": 400, "blocked": 503}.get(result["status"], 200)
            _json_response(self, status, result)
            return

        if self.path == "/market-evidence/retrieve":
            if not normalize_exterior_grade(payload.get("exterior_grade")):
                _json_response(self, 200, exterior_grade_error_response())
                return
            _json_response(
                self,
                200,
                retrieve_current_market_evidence(
                    confirmed_device=payload.get("confirmed_device"),
                    exterior_grade=payload.get("exterior_grade"),
                ),
            )
            return

        if self.path == "/merge-and-grade":
            yolo_items = [YoloDetection(**item) for item in payload.get("yolo_detections", [])]
            damage = [
                MergedDamage(
                    damage_type=item.damage_type,
                    view=item.view,
                    severity="unknown",
                    support="yolo_only",
                    verification="confirmed",
                    grade_affecting=True,
                    manual_review=False,
                    confidence=item.confidence,
                    bounding_box_xyxy=item.bounding_box_xyxy,
                )
                for item in yolo_items
                if item.damage_type is not None
            ]
            _json_response(self, 200, asdict(grade_from_atomic_damage(damage)))
            return

        if self.path == "/live-valuation":
            grade = normalize_exterior_grade(payload.get("exterior_grade"))
            if not grade:
                _json_response(self, 200, exterior_grade_error_response())
                return
            ok, error, device = canonicalize_confirmed_device(payload.get("confirmed_device"))
            if not ok or device is None:
                _json_response(self, 200, {"status": "error", "error": error, "value_low": None, "value_high": None})
                return
            valuation_basis = payload.get("valuation_basis", "manual_grade")
            if valuation_basis == "exterior_scan":
                assessment_basis = verify_receipt(payload.get("assessment_receipt"), device, grade)
                if not assessment_basis:
                    _json_response(self, 409, {
                        "status": "pending", "error": "Scan evidence is missing or expired. Re-run the exterior scan.",
                        "value_low": None, "value_high": None,
                    })
                    return
            elif valuation_basis == "manual_grade":
                assessment_basis = "manual_grade"
            else:
                _json_response(self, 400, {"status": "error", "error": "Unknown valuation basis."})
                return
            market = retrieve_current_market_evidence(confirmed_device=device, exterior_grade=grade)
            result = build_live_estimate(device, grade, market)
            result["assessment_basis"] = assessment_basis
            _json_response(self, 200, result)
            return

        _json_response(self, 404, {"error": "not_found"})


def run(host: str = "0.0.0.0", port: int = 8765) -> None:
    port = int(os.environ.get("PORT", str(port)))
    server = ThreadingHTTPServer((host, port), ReValueHandler)
    print(f"ReValue Phase 6A.3 backend listening on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()


