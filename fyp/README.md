# ReValue AI FYP1 development

Use the `fyp1-development` branch of YANKEY-CODE/ReValue-AI. The backend serves the v1.16.1 HTML app and API. Work in this checkout and keep phone images, labelled datasets and credentials outside Git. Review authorship, licenses and compatibility before importing anything from the reference repository.

## Reproducible development setup

The pinned environment was tested with Python 3.12 on Linux x86-64 and CPU. From the repository root in Bash:

```bash
git switch fyp1-development
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install 'torch==2.15.0+cpu' 'torchvision==0.29.2+cpu' --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r fyp/requirements-linux-cpu.txt
python -m pip check
export YOLO_CONFIG_DIR="$PWD/.revalue-runtime/yolo"
export MPLCONFIGDIR="$PWD/.revalue-runtime/matplotlib"
export YOLO_AUTOINSTALL=false OMP_NUM_THREADS=2
mkdir -p "$YOLO_CONFIG_DIR" "$MPLCONFIGDIR"
```

For macOS, Windows or CUDA, install a matching PyTorch and Torchvision pair using the official PyTorch installation instructions, then install `backend/requirements.txt` and `PyYAML==6.0.3` in a Python 3.12 virtual environment. Record the resolved versions for comparison runs. The pinned file is for the tested Linux CPU environment.

Run the automated checks and start the server from the repository root:

```bash
set -e
for test in backend/tests/*.py; do REVALUE_TEST_REAL_MODEL=1 python "$test"; done
python fyp/test_evaluate_detection.py
python -m backend.src.server
```

Open `http://127.0.0.1:8765` and confirm `/health` returns `{"status":"ok", ...}`. Choose **Value Another Phone**, search the catalogue, confirm storage, attach front, back, camera, left and right photos, then choose **Analyze Exterior**. Test replacing a photo after analysis. The previous grade and valuation should be cleared. To check QR capture across two devices, run on a trusted network and open the app via a host address reachable from both. The localhost address is only reachable from the server machine. Use consented test photos. Uploads accept JPEG, PNG and WebP up to 8 MiB and 16 megapixels each.

Without a Gemini key, the catalogue, YOLO and eligible local fallback valuations can run independently. For authorized live integration tests, configure `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) in the server environment, set `REVALUE_GEMINI_MODEL` to an available Gemini model, and allow access to Google's Gemini API. The server does not automatically load .env files. Gemini verification may involve sending the selected photos to the API. Verify account access and search grounding separately. Demo Mode contains illustrative values and internal diagnostics. Shop offers and conversations are simulations.

The default detector is the bundled YOLO11n. For trusted compatible YOLO weights, set `REVALUE_DETECTOR_WEIGHTS=/path/to/weights.pt` and optionally `REVALUE_DETECTOR_IMGSZ=960`, then restart. A detector adapter can use the callable boundary in `analyze_exterior`: return view-specific candidates and pixel coordinates using `YoloDetection`. The RT-DETR option in the evaluator is separate from the server's default YOLO loader.

## Historical baseline

The bundled report records 173 held-out images and 414 annotations, with overall precision 0.495, recall 0.486, mAP@50 0.426 and mAP@50–95 0.181. It reports crack precision 0.369 and recall 0.230, and scratch precision 0.621 and recall 0.743. These figures are historical and have not been independently rerun. The source is [MODEL_EVALUATION_v0.2.txt](../backend/models/MODEL_EVALUATION_v0.2.txt).

## Run a held-out detection comparison

Prepare a permitted dataset outside the checkout with local image directories in its YAML. Use a path relative to the YAML or an absolute path. Each image belongs under an `images/` directory with a matching YOLO box label under `labels/`. Use an explicit empty label file for each reviewed clean negative.

```yaml
path: /path/to/dataset
train: images/train
val: images/val
test: images/test
names: [generic_crack, scratch]
```

Test-only data can omit `train` and `val`. When provided, the evaluator checks train/validation directories for exact copies of test images. Manually audit session-level separation and near duplicates regardless. Both classes must be represented in held-out ground truth.

```bash
python fyp/evaluate_detection.py \
  --data /path/to/data.yaml --dataset-version phones-v1 \
  --models backend/models/revalue_exterior_yolo11n_v0.2.pt \
  --imgsz 640 --confidence 0.25 --device cpu --batch 1 \
  --output fyp/results/baseline-640

python fyp/evaluate_detection.py \
  --data /path/to/data.yaml --dataset-version phones-v1 \
  --models backend/models/revalue_exterior_yolo11n_v0.2.pt \
  --imgsz 960 --confidence 0.25 --device cpu --batch 1 \
  --output fyp/results/baseline-960
```

For a same-resolution architecture comparison, pass `--models /local/yolo11n.pt /local/yolo11s.pt /local/rtdetr.pt --family yolo yolo rtdetr` with checkpoints fine-tuned on the phone classes. Use existing, trusted local checkpoint files. The pinned Ultralytics version may fetch a display font on first validation when it is absent from the runtime cache. The evaluator does not download datasets or model weights.

Each output directory contains `summary.csv`, `per_class.csv` and `run_manifest.json`. Precision, recall, F1 and TP/FP/FN use the fixed confidence threshold and class-aware IoU 0.50 matching. The summary pools the counts across classes. AP is computed separately over ranked detections at confidence ≥0.001. The files also include false detections on reviewed negatives, model and data hashes, and the validator's inference, preprocessing and postprocessing time per image. Exclude upload, startup and Gemini latency from that comparison. Use the [evaluation protocol](EVALUATION_PROTOCOL.md) for study design and the [technical handoff](TECHNICAL_HANDOFF.md) for project status.
