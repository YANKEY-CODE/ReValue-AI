# Local qualitative model comparison

This tool opens a separate site on `127.0.0.1:8766` using the existing Windows Python 3.12 `.venv`. It compares ReValue YOLO11n v0.2 and experimental Houdan YOLO11s v1.0.0. The live ReValue application keeps its existing detector and port 8765.

## Start on Windows

In Windows PowerShell, update the clean development checkout and launch the comparison.

```powershell
Set-Location "$env:USERPROFILE\ReValue-AI"
git pull --ff-only origin fyp1-development
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\compare-models.ps1
```

Use your installation folder if it differs. On the first launch, the tool fetches `best.pt` from the pinned release and saves it to `%LOCALAPPDATA%\ReValueAI\experimental\houdan-v1.0.0\best.pt`. It checks SHA-256 against `c2c32004a2bbfae390fe439e01a1bdd00fed4ad21270b9cf2caedd5f0e0bf26c` before writing the download and checks the exact bytes again before restricted PyTorch loading. Keep the checkpoint outside the checkout. [Official release](https://github.com/houdan-hub/phone-defect-detection/releases/tag/v1.0.0) · [Checkpoint and AGPL-3.0 review](HOUDAN_V1_MODEL_REVIEW.md)

When the terminal prints `ReValue model comparison is ready at http://127.0.0.1:8766`, use the browser tab or open that URL yourself. Keep PowerShell running and use **Ctrl+C** to stop. If GitHub is unavailable, obtain the release asset through an authorized connection and supply its private path with `-HoudanWeights 'C:\path\to\best.pt'`. A bad cache fails the hash check. Move the cache file out of that folder before retrying the automatic download. If port 8766 is occupied, add `-Port 8767` and use the printed URL.

## Compare and export

1. Use **Smartphone photos** to select up to 20 authorized JPEG, PNG or WebP images. Each must be no larger than 8 MiB or 16 megapixels.
2. Select **Compare photos**. Each result shows the original photo preview and both models’ boxes, labels and confidence scores. The models receive the same upright input pixels with 640 × 640 inference, confidence threshold 0.25, class-aware NMS at IoU 0.70, batch size one and FP32 on CPU.
3. Read the crack and scratch counts for each model. Houdan `crack` is mapped to `generic_crack` in the comparison. The raw class remains visible in the detail list and exports. Houdan `bump` and `paint` are shown separately.
4. Download **Export CSV** for a spreadsheet or **Export JSON** for the full structured record. CSV has one row per prediction, and a summary row per model when it predicts no boxes. Counts and times repeat across a model’s rows for that photo, so group by photo and model before aggregating. JSON groups predictions by photo and model and includes settings, runtime versions and model hashes. Exports include filenames, source SHA-256 and coordinates in upright source pixels. They omit photo bytes. Keep private exports outside Git.

**Interpretation.** Counts describe predicted boxes. Overlapping boxes, missed defects and different class definitions can change the counts. An empty result means the model emitted no boxes at the chosen settings. A higher confidence score or more boxes cannot establish comparative accuracy. CPU inference measures the detector forward stage. Whole prediction also includes model preprocessing and postprocessing. The first request warms up both models once outside the displayed timings. The tool alternates which model runs first on successive photos. Laptop load, thermal state and other software can affect a single timing. Use an independently annotated holdout for any accuracy claim. [Benchmark protocol](EVALUATION_PROTOCOL.md)

For development on Linux, use `python -m fyp.model_comparison --houdan-weights /path/outside/repo/best.pt --no-browser` inside the project environment. Run `python -m unittest fyp.test_model_comparison` for automated checks. For the real CPU regression, set `REVALUE_HOUDAN_TEST_WEIGHTS` to the verified external checkpoint. With the local server and Playwright running, use `node fyp/model_comparison_smoke.cjs` to verify the browser workflow and exports. Set `REVALUE_COMPARISON_URL` for a custom port and `CHROMIUM_PATH` for a system Chromium.

## Verification

On 20 November 2026, Linux checks passed for the official asset download and SHA-256, blocked invalid uploads and checkpoint files, real inference with both models, and the Chromium multi-photo and export workflow. A PowerShell test used a simulated Windows `.venv` layout and the same PyTorch and Torchvision versions as the Windows installer. Both detectors also ran on two CC BY 4.0 Broken Interfaces screen crops as an input smoke test. Their images and outputs stayed local. Native Windows startup and browser opening still need a laptop check. [Broken Interfaces source and attribution](HOUDAN_V1_MODEL_REVIEW.md#private-qualitative-comparison)
