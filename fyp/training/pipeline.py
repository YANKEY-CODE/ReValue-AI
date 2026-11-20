"""Drive-backed Colab training using the ReValue frozen benchmark contract."""
import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image

BENCH = Path(__file__).resolve().parents[1] / "benchmark"
sys.path.insert(0, str(BENCH))
from dataset import CLASSES, REPO, SPLITS, digest, private_path, read_json, write_json
from evaluate import BUNDLED_SHA, evaluate, frozen_test

BASE = REPO / "backend/models/revalue_exterior_yolo11n_v0.2.pt"
INITIAL_SHA = {
    "n": "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1",
    "s": "85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5",
}
SCALES = tuple(INITIAL_SHA)
CONTROL = REPO / "fyp/training-control.yaml"


def prepare(root, work):
    """Use explicit manifests. Adjacent unreviewed files cannot enter training."""
    frozen_test(root)
    manifest = read_json(root / "manifest.json")
    if digest(BASE) != BUNDLED_SHA:
        raise ValueError("Bundled baseline checksum mismatch.")
    work.mkdir(parents=True, exist_ok=True)
    config = {"path": str(work), "names": list(CLASSES)}
    for split in SPLITS:
        rows = manifest["splits"][split]
        classes = {b["label"] for r in rows for b in r["annotation"]["boxes"]}
        if classes != set(CLASSES) or not any(r["annotation"]["kind"] == "clean" for r in rows):
            raise ValueError(f"{split} requires both classes and verified clean negatives.")
        paths = []
        for r in rows:
            if not all(r.get(k, "").strip() for k in ("source", "source_asset", "attribution", "license_terms")):
                raise ValueError(f"Missing source rights or attribution for {r['id']}.")
            path = root / "images" / split / (r["id"] + ".png")
            with Image.open(path) as im:
                im.load()
                if im.size != (r["width"], r["height"]) or im.format != "PNG":
                    raise ValueError(f"Invalid frozen pixels for {r['id']}.")
            paths.append(str(path))
        listing = work / f"{split}.txt"
        listing.write_text("\n".join(paths) + "\n", encoding="utf-8")
        config[split] = str(listing)
    path = work / "approved.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


def recipe(root, scale, initial):
    import torch
    import ultralytics
    return dict(manifest=digest(root / "manifest.json"), initial_weights=digest(initial),
                scale=scale, revision=subprocess.check_output(["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True).strip(),
                python=platform.python_version(), torch=str(torch.__version__), cuda=torch.version.cuda,
                gpu=torch.cuda.get_device_name(0), ultralytics=ultralytics.__version__,
                options=dict(yaml.safe_load(CONTROL.read_text()), epochs=100, patience=100, imgsz=640,
                             seed=17, batch=8, optimizer="AdamW", lr0=.001, deterministic=True,
                             workers=2, device=0, plots=True, save=True, save_period=10))


def train(root, work, scale, initial):
    import torch
    from ultralytics import YOLO
    config = prepare(root, work)
    if not torch.cuda.is_available():
        raise RuntimeError("Enable a free Colab GPU before training.")
    baseline = work / "baseline-val" / "summary.json"
    if not baseline.exists() or read_json(baseline)["manifest_sha256"] != digest(root / "manifest.json"):
        raise ValueError("Run the baseline validation cell for this frozen dataset first.")
    if digest(initial) != INITIAL_SHA[scale]:
        raise ValueError("Official v8.4.0 COCO initialization hash mismatch.")
    experiment = recipe(root, scale, initial)
    name = f"yolo11{scale}-control"
    run = work / name
    spec = work / (name + ".json")
    done = work / (name + "-complete.json")
    best = run / "weights/best.pt"
    last = run / "weights/last.pt"
    if spec.exists() and read_json(spec) != experiment:
        raise ValueError("Run settings, runtime or dataset changed. Choose a new experiment folder.")
    if run.exists() and not spec.exists():
        raise ValueError("Existing run has no matching experiment record.")
    if done.exists():
        if not spec.exists() or read_json(done)["sha256"] != digest(best):
            raise ValueError("Completed checkpoint or recipe changed.")
        return best
    write_json(spec, experiment)
    if run.exists() and not last.exists():
        raise ValueError("Interrupted before last.pt. Archive the interrupted run and start in a fresh folder.")
    model = YOLO(str(last if last.exists() else initial))
    if model.task != "detect" or model.model.yaml.get("scale") != scale:
        raise ValueError("Initialization architecture differs from requested detector.")
    if last.exists():
        model.train(resume=True, data=str(config), device=0)
    else:
        model.train(data=str(config), project=str(work), name=name, exist_ok=True, **experiment["options"])
    if not best.is_file() or YOLO(str(best)).names != dict(enumerate(CLASSES)):
        raise ValueError("Expected a two-class best.pt.")
    write_json(done, {"sha256": digest(best)})
    return best


def comparison(root, work, final):
    prepare(root, work)
    split = "test" if final else "val"
    destination = work / ("final-test" if final else "baseline-val")
    models = {}
    if final:
        for scale in SCALES:
            name = f"yolo11{scale}-control"
            path = work / name / "weights/best.pt"
            if (read_json(work / (name + ".json"))["manifest"] != digest(root / "manifest.json")
                    or digest(path) != read_json(work / (name + "-complete.json"))["sha256"]):
                raise ValueError("Experimental checkpoint or dataset differs from training.")
            models[name] = path
    expected = {"revalue-yolo11n": BUNDLED_SHA, **{k: digest(v) for k, v in models.items()}}
    if destination.exists():
        summary = read_json(destination / "summary.json")
        if summary["manifest_sha256"] != digest(root / "manifest.json") or summary["weights_sha256"] != expected:
            raise ValueError("A different run owns this result directory.")
        return destination
    # Keep incomplete results out of the reusable final location.
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(dir=work) as tmp:
        out = Path(tmp) / "metrics"
        evaluate(root, out, None, 640, candidates=models, split=split)
        out.rename(destination)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "baseline", "train", "compare"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--scale", choices=SCALES)
    parser.add_argument("--initial", type=Path)
    args = parser.parse_args()
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    root, work = private_path(args.dataset), private_path(args.work)
    if root.is_relative_to(work) or work.is_relative_to(root):
        parser.error("Keep the frozen export and experiment directory separate.")
    if args.action == "train":
        if not args.initial or not args.scale:
            parser.error("Training requires --scale and --initial (trusted COCO initialization).")
        print(train(root, work, args.scale, args.initial))
    elif args.action == "prepare":
        print(prepare(root, work))
    else:
        print(comparison(root, work, args.action == "compare"))
