"""Private, localhost-only visual comparison of the two fixed detectors."""

from __future__ import annotations

import argparse
from base64 import b64encode
from hashlib import file_digest, sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from time import perf_counter
from urllib.request import urlopen
import webbrowser

from backend.src.image_upload import MAX_IMAGE_BYTES, decode_image
from backend.src.schemas import ImageInput
from backend.src.yolo_detector import DEFAULT_MODEL_PATH, RAW_CLASS_NAMES

from .benchmark.checkpoints import BUNDLED_SHA, HOUDAN_BYTES, HOUDAN_SHA, HOUDAN_URL, load_houdan, verify_houdan_bytes

ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
PORT = 8766
CPU_THREADS = 2
PREDICT = dict(imgsz=640, conf=0.25, iou=0.70, device="cpu", quantize=32, rect=False,
               batch=1, max_det=300, agnostic_nms=False, augment=False, save=False, verbose=False)
MODELS = {
    "revalue": {"name": "ReValue YOLO11n v0.2", "sha256": BUNDLED_SHA,
                "classes": ["generic_crack", "scratch"]},
    "houdan": {"name": "Houdan YOLO11s v1.0.0 (experimental)", "sha256": HOUDAN_SHA,
               "classes": ["generic_crack", "scratch", "bump", "paint"], "source": HOUDAN_URL},
}


def houdan_checkpoint(supplied: Path | None = None) -> Path:
    appdata = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share")
    path = (supplied or appdata / "ReValueAI" / "experimental" / "houdan-v1.0.0" / "best.pt").resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Store the experimental Houdan checkpoint outside the repository.")
    if supplied or path.is_file():
        if not path.is_file():
            raise ValueError(f"Houdan checkpoint missing at {path}.")
        return path

    print("Downloading the official Houdan v1.0.0 release checkpoint...", flush=True)
    with urlopen(HOUDAN_URL, timeout=40) as response:
        data = response.read(HOUDAN_BYTES + 1)
    verify_houdan_bytes(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as download:
        temporary = Path(download.name)
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def model_readout(key, prediction, wall_ms):
    counts = dict.fromkeys(MODELS[key]["classes"], 0)
    detections = []
    for x1, y1, x2, y2, confidence, class_id in prediction.boxes.data.tolist():
        raw = prediction.names[int(class_id)]
        label = "generic_crack" if key == "houdan" and raw == "crack" else raw
        counts[label] += 1
        detections.append({"raw_class": raw, "comparison_class": label, "confidence": confidence,
                           "xyxy_px": [x1, y1, x2, y2]})
    return {"counts": counts, "detections": detections, "cpu_inference_ms": prediction.speed["inference"],
            "cpu_predict_wall_ms": wall_ms}


class InvalidPhoto(ValueError):
    pass


class ComparisonRunner:
    def __init__(self, models, versions):
        self.models = models
        self.metadata = {"schema_version": 1, "comparison_type": "qualitative", "settings": PREDICT,
                         "models": MODELS, "runtime": {**versions, "cpu_threads": CPU_THREADS},
                         "timing": "One comparable warm-up per model. Timed inference excludes image decoding, checkpoint loading, and warm-up."}
        self._lock = Lock()
        self._images_processed = 0

    def compare(self, upload):
        try:
            image = decode_image(ImageInput("unknown", bytes_b64=b64encode(upload).decode("ascii")))
        except ValueError as error:
            raise InvalidPhoto(str(error).replace(" for unknown", "")) from error
        return self._compare(image, sha256(upload).hexdigest())

    def _compare(self, image, source_sha256):
        import numpy as np

        frame = np.asarray(image)[:, :, ::-1].copy()  # Upright RGB to BGR; both models get the same pixels.
        results = {}
        with self._lock:
            if self._images_processed == 0:
                for model in self.models.values():
                    model.predict(frame.copy(), **PREDICT)
            order = tuple(self.models) if self._images_processed % 2 == 0 else tuple(reversed(self.models))
            for key in order:
                input_frame = frame.copy()
                start = perf_counter()
                prediction = self.models[key].predict(input_frame, **PREDICT)[0]
                results[key] = model_readout(key, prediction, (perf_counter() - start) * 1000)
            self._images_processed += 1

        # A preview from the exact decoded orientation keeps the original-pixel box coordinates aligned.
        width, height = image.size
        image.thumbnail((1200, 1200))
        preview = BytesIO()
        image.save(preview, format="JPEG", quality=88)
        return {"image": {"width": width, "height": height, "source_sha256": source_sha256},
                "preview_jpeg_base64": b64encode(preview.getvalue()).decode("ascii"), "models": results}


def load_runner(path):
    os.environ["YOLO_CONFIG_DIR"] = str(ROOT / ".revalue-runtime" / "comparison" / "yolo")
    os.environ["MPLCONFIGDIR"] = str(ROOT / ".revalue-runtime" / "comparison" / "matplotlib")
    os.environ.update(YOLO_AUTOINSTALL="false", OMP_NUM_THREADS=str(CPU_THREADS), MKL_NUM_THREADS=str(CPU_THREADS))
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

    import cv2
    import torch
    import ultralytics
    from ultralytics import YOLO, settings

    settings.update({"sync": False})
    torch.set_num_threads(CPU_THREADS)
    cv2.setNumThreads(CPU_THREADS)
    with DEFAULT_MODEL_PATH.open("rb") as stream:
        if file_digest(stream, "sha256").hexdigest() != BUNDLED_SHA:
            raise ValueError("The bundled ReValue checkpoint differs from the registered v0.2 SHA-256.")
    houdan = load_houdan(path, YOLO, torch)
    revalue = YOLO(str(DEFAULT_MODEL_PATH))
    if revalue.task != "detect" or revalue.names != RAW_CLASS_NAMES:
        raise ValueError("The bundled ReValue detector has unexpected classes.")
    return ComparisonRunner({"revalue": revalue, "houdan": houdan},
                            {"torch": str(torch.__version__), "ultralytics": ultralytics.__version__})


class ComparisonHandler(BaseHTTPRequestHandler):
    def _send(self, status, content, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; "
                         "img-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status, response):
        self._send(status, json.dumps(response, allow_nan=False).encode("utf-8"), "application/json")

    def _local_request(self):
        host = f"{HOST}:{self.server.server_port}"
        if self.headers.get("Host") == host and self.headers.get("Origin", f"http://{host}") == f"http://{host}":
            return True
        self._json(403, {"error": "Open the comparison at its local 127.0.0.1 address."})
        return False

    def do_GET(self):
        if not self._local_request():
            return
        if self.path == "/":
            self._send(200, Path(__file__).with_suffix(".html").read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/model_comparison.js":
            self._send(200, Path(__file__).with_suffix(".js").read_bytes(), "text/javascript; charset=utf-8")
        elif self.path == "/metadata":
            self._json(200, self.server.runner.metadata)
        else:
            self._json(404, {"error": "Page not found."})

    def do_POST(self):
        if not self._local_request():
            return
        if self.path != "/compare":
            self._json(404, {"error": "Page not found."})
            return
        if self.headers.get("Content-Type") != "application/octet-stream" or self.headers.get("Transfer-Encoding"):
            self._json(415, {"error": "Send one photo using the comparison page."})
            return
        length = self.headers.get("Content-Length", "")
        if not length.isascii() or not length.isdecimal() or len(length) > 10 or not int(length):
            self._json(400, {"error": "No complete photo was received."})
            return
        if int(length) > MAX_IMAGE_BYTES:
            self._json(413, {"error": "Use a photo of 8 MiB or less."})
            return
        self.connection.settimeout(30)
        try:
            upload = self.rfile.read(int(length))
        except TimeoutError:
            upload = b""
        if len(upload) != int(length):
            self._json(400, {"error": "The photo upload was incomplete."})
            return
        try:
            result = self.server.runner.compare(upload)
        except InvalidPhoto as error:
            self._json(400, {"error": str(error)})
        except Exception as error:
            self.log_error("Prediction failed: %s", error)
            self._json(503, {"error": "Both predictions could not complete. See the comparison terminal for details."})
        else:
            self._json(200, result)


def open_browser(url):
    try:
        if webbrowser.open(url):
            return
    except (OSError, webbrowser.Error):
        pass
    print(f"Open {url} in your browser.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--houdan-weights", type=Path, help="Use the verified best.pt from a path outside this checkout.")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        print("Loading the fixed CPU detectors for qualitative comparison...", flush=True)
        runner = load_runner(houdan_checkpoint(args.houdan_weights))
        with ThreadingHTTPServer((HOST, args.port), ComparisonHandler) as server:
            server.runner = runner
            url = f"http://{HOST}:{server.server_port}"
            print(f"ReValue model comparison is ready at {url}\nPress Ctrl+C to stop.", flush=True)
            if not args.no_browser:
                Thread(target=open_browser, args=(url,), daemon=True).start()
            server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        print(f"Comparison could not start: {error}", file=sys.stderr)
        print("See fyp/MODEL_COMPARISON.md for checkpoint and local setup help.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
