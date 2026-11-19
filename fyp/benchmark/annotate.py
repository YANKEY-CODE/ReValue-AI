"""Serve the private annotation workspace on this computer only."""

import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit

from dataset import approved_annotation, key, practice_ids, private_path, read_json, records, update_record, write_json
from propose import proposal_for


def handler(root, port):
    origin = f"http://127.0.0.1:{port}"
    practice_only = (root / "practice_only.json").is_file()

    class AnnotationHandler(BaseHTTPRequestHandler):
        def send(self, body, content_type, code=200):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def json(self, data, code=200):
            self.send(json.dumps(data).encode(), "application/json", code)

        def local_request(self):
            if self.headers.get("Host") != f"127.0.0.1:{port}" or (
                self.command == "POST" and self.headers.get("Origin") != origin
            ):
                self.json({"error": "Open the annotator at " + origin}, 403)
                return False
            return True

        def do_GET(self):
            if not self.local_request():
                return
            parts = urlsplit(self.path).path.strip("/").split("/")
            if parts == [""]:
                self.send(Path(__file__).with_name("annotation.html").read_bytes(), "text/html; charset=utf-8")
            elif parts == ["records"]:
                reserved = practice_ids(root)
                self.json([
                    {"id": row["id"], "annotated": bool(row["annotation"]),
                     "review": ({"decision": row["review"]["decision"]} if row["review"] and (
                         row["review"]["decision"] == "revise" or approved_annotation(row)
                     ) else None),
                     "split": row["split"], "practice": row["id"] in reserved}
                    for row in records(root).values()
                ])
            elif len(parts) == 2 and parts[0] == "proposal":
                try:
                    self.json(proposal_for(root, parts[1]))
                except (ValueError, OSError):
                    self.json({"error": "No proposal is available for this training photo."}, 404)
            elif len(parts) == 2 and parts[0] in ("record", "image"):
                try:
                    identifier = key(parts[1])
                    path = root / "records" / f"{identifier}.json"
                    raw = path.read_bytes()
                    if parts[0] == "image":
                        self.send((root / "images" / f"{identifier}.png").read_bytes(), "image/png")
                    else:
                        row = json.loads(raw)
                        fields = ("id", "license_terms", "attribution", "view", "width", "height",
                                  "annotation", "review", "split")
                        self.json({
                            **{f: row[f] for f in fields}, "revision": sha256(raw).hexdigest(),
                            "practice_only": practice_only,
                            "proposal_available": row["split"] == "train" and row.get("model_assisted", False)
                            and (root / "proposals" / f"{identifier}.json").is_file(),
                        })
                except (ValueError, OSError):
                    self.json({"error": "Image record unavailable."}, 404)
            else:
                self.json({"error": "Unknown page."}, 404)

        def do_POST(self):
            if not self.local_request():
                return
            try:
                action, identifier = urlsplit(self.path).path.strip("/").split("/")
                if practice_only and action != "annotate":
                    raise ValueError("Practice queues accept independent annotations only.")
                length = int(self.headers["Content-Length"])
                if not (0 < length <= 100_000):
                    raise ValueError("Invalid submission size.")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("Expected an object.")
                path = root / "records" / f"{key(identifier)}.json"
                raw = path.read_bytes()
                if data.get("revision") != sha256(raw).hexdigest():
                    self.json({"error": "This record changed. Reload before submitting."}, 409)
                    return
                write_json(path, update_record(json.loads(raw), action, data))
                self.json({"ok": True})
            except (TypeError, ValueError, KeyError, OSError) as exc:
                self.json({"error": str(exc)}, 400)

    return AnnotationHandler


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8769)
    args = parser.parse_args()
    print(f"Annotation workspace at http://127.0.0.1:{args.port}", flush=True)
    HTTPServer(("127.0.0.1", args.port), handler(private_path(args.root), args.port)).serve_forever()
