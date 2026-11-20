# ReValue AI handoff for Codex Local on Windows

Handoff recorded on 20 November 2026. Continue dataset work on **`training/colab-yolo11`** in `YANKEY-CODE/ReValue-AI`. The last application and tooling checkpoint before this document was `f19ffb1`. The priority on the laptop is to inspect the user’s local SSGD ZIP, record the actual counts and clear the dataset review requirements.

## Repository state

| Branch | Relevant checkpoint | Contents |
| --- | --- | --- |
| `training/colab-yolo11` | `f19ffb1` plus this handoff | Windows SSGD intake, private benchmark workflow, Colab notebook, YOLO11n/YOLO11s training and matched evaluation. Includes the app as of `602828c`. |
| `fyp1-development` | `602828c` | App, Windows launcher and protected Docker/Render supervisor demo configuration. |
| `design/revalue-premium-v2` | `bb544e0` | Separate editorial redesign and desktop/mobile visual review. Switch to this branch only when reviewing that design. |
| `main` | `8dfe58e` | Upstream application baseline. The cloud-only branch `work` pointed at the same commit. |

All listed checkpoints were verified on GitHub. Only the training branch is needed for SSGD. Repository status was clean before writing this document. [GitHub repository](https://github.com/YANKEY-CODE/ReValue-AI)

## Open the project in Codex Local

On Windows, open Codex, choose a **Local** workspace and select your ReValue folder. Open a Local session in that folder. Ask Codex to read `HANDOFF.md` and `fyp/training/SSGD_WINDOWS.md` and use the SSGD ZIP at `C:\Users\USER\Downloads\SSGD.zip`. A terminal opened in the Local workspace should resolve both the repository and the ZIP using Windows paths.

If `C:\Users\USER\ReValue-AI` already exists, start by checking its status. If you have local changes or want an isolated checkout, keep that folder and use the fresh-clone command with the destination `ReValue-AI-training`. A clean existing checkout that already tracks the training branch can update with `git pull --ff-only origin training/colab-yolo11` while on that branch. Check the branch first because that command updates the checked-out branch.

For a new clone, run from PowerShell. Use an unused destination.

```powershell
Set-Location $env:USERPROFILE
git clone --branch training/colab-yolo11 https://github.com/YANKEY-CODE/ReValue-AI.git ReValue-AI-training
Set-Location .\ReValue-AI-training
git status --short --branch
Get-Item -LiteralPath 'C:\Users\USER\Downloads\SSGD.zip' | Select-Object FullName, Length
```

If using this new folder, replace `C:\Users\USER\ReValue-AI` in the SSGD guide with the new path. That guide offers a separate-worktree option for an existing checkout. From a fresh training checkout, you can run the intake script directly and skip the worktree commands.

## Set up and run locally

Use Windows 10 or 11 x64, Git for Windows 2.23 or newer, PowerShell 5.1 or 7, and 64-bit CPython 3.12. Install Git and Python if needed. [Windows prerequisite and troubleshooting guide](WINDOWS_SETUP.md)

The app uses a static frontend and a Python backend. The Windows CPU environment pins PyTorch `2.14.1+cpu`, Torchvision `0.29.1+cpu`, Ultralytics `8.4.215`, OpenCV, Pillow, PyYAML and the backend libraries. Node.js and Playwright are optional for browser regression tests. Colab uses its CUDA-enabled Python environment. [Windows CPU dependency pins](backend/requirements-windows-cpu.txt) · [Linux dependency pins](fyp/requirements-linux-cpu.txt)

If this checkout already has a working `.venv`, skip installation and run the launcher check below. For a fresh training checkout, create the venv and install dependencies directly. This keeps the training branch checked out because `setup-windows.ps1` selects `fyp1-development`.

```powershell
py -3.12 -m venv .venv
$python = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
& $python -m pip install --no-deps --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu' 'torchvision==0.29.1+cpu'
& $python -m pip install --only-binary=:all: -r .\backend\requirements-windows-cpu.txt
& $python -m pip check
```

From the repository root, run the installation check and then launch the local app. Use a second terminal for the comparison tool. The first comparison run downloads and verifies experimental Houdan weights from its official release and caches them outside Git.

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-revalue.ps1 -Check
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-revalue.ps1

# In a separate terminal at the repository root
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\compare-models.ps1
```

The app runs at [127.0.0.1:8765](http://127.0.0.1:8765). Qualitative comparison runs at [127.0.0.1:8766](http://127.0.0.1:8766). The annotation workflow runs at [127.0.0.1:8769](http://127.0.0.1:8769) once started with a private dataset root. Stop each server with **Ctrl+C** in its terminal. [Comparison guide](fyp/MODEL_COMPARISON.md) · [Annotation guide](fyp/BENCHMARK_HANDOFF.md)

### Environment variables

The Windows launcher supplies its own local runtime directories and uses the bundled YOLO11n for CPU inference. No API credentials are required for the default phone assessment or SSGD intake.

| Variable | Use |
| --- | --- |
| `YOLO_CONFIG_DIR`, `MPLCONFIGDIR` | Writable Ultralytics and Matplotlib directories. Windows app/comparison launchers manage them under ignored `.revalue-runtime`. |
| `YOLO_AUTOINSTALL`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` | The app launcher sets `YOLO_AUTOINSTALL=false` and defaults both CPU thread settings to 2. |
| `GEMINI_API_KEY` or `GOOGLE_API_KEY`, `REVALUE_GEMINI_MODEL` | Optional credentials and model override for Gemini features. Set secrets locally where needed. |
| `REVALUE_AUDITED_MARKET_CSV` | Optional path to an operator-reviewed market CSV. A report may legitimately show insufficient market evidence. |
| `REVALUE_DETECTOR_WEIGHTS`, `REVALUE_DETECTOR_IMGSZ` | Experimental overrides for custom backend execution. The normal Windows launcher clears them so the bundled model runs at its default setting. |
| `REVALUE_DEMO_PASSWORD`, `REVALUE_PUBLIC_ORIGIN`, `PORT` | Hosted supervisor configuration. Render can supply `RENDER_EXTERNAL_URL` for the public HTTPS origin. The normal Windows launcher binds to 127.0.0.1:8765. |
| `REVALUE_TEST_REAL_MODEL`, `REVALUE_HOUDAN_TEST_WEIGHTS`, `PYTHONPATH` | Opt into real model tests and, for the comparison test, supply the path to a hash-verified Houdan checkpoint. Set `PYTHONPATH` as shown for direct benchmark test imports. |
| `REVALUE_SMOKE_URL`, `REVALUE_COMPARISON_URL`, `CHROMIUM_PATH`, `REVALUE_DEMO_URL` | Optional browser test overrides for local URLs, Chromium location and the supervisor HTTPS URL. |

Keep credentials and private paths in the active local session or hosting secret store. Review the [market evidence workflow](fyp/FYP1_SYSTEM_HANDOFF.md) and [hosted supervisor settings](DEPLOYMENT.md) before configuring the optional features.

### Check the local installation and tests

Run the launcher check above for bundled CPU inference and localhost HTTP. Run the following from the repository root once the environment is installed.

```powershell
$python = Join-Path (Get-Location).Path '.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD\fyp\training;$PWD\fyp\benchmark;$PWD\fyp"
& $python -m unittest test_prepare_ssgd test_pipeline test_benchmark test_import_practice test_evaluate_detection
& $python -m unittest backend.tests.test_supervisor fyp.test_model_comparison
node .\fyp\test_decision_support.cjs
```

With Playwright and Chromium installed, run `node fyp/browser_smoke.cjs` while the app runs and `node fyp/model_comparison_smoke.cjs` while comparison runs. [Browser and backend test details](fyp/README.md)

The handoff recheck on Linux passed 19 dataset and training-tool tests, 69 backend tests with five subtests and real CPU inference enabled, and the JavaScript quote decision checks. The Windows commands and real SSGD archive still need to run on the laptop.

## Status and next local work

- **Application.** Earlier Linux checks covered five-upload assessment, real bundled YOLO11n CPU inference, report generation, quote comparison and the experimental comparison tool. The supervisor entry point and Docker image were checked through local HTTPS. A public host and public HTTPS URL are still pending. The laptop remains the place to verify native Windows behavior. [FYP1 system status](fyp/FYP1_SYSTEM_HANDOFF.md) · [Deployment steps](DEPLOYMENT.md)
- **SSGD.** The ZIP path is known and the acquisition source advertises academic use only. The cloud session could not read the Windows archive, so counts, corrupt entries, duplicate candidates, exact folder layout and GPU availability on that machine are pending. Run the intake script with the real ZIP, inspect the printed `intake.json` and `audit.json`, then run the guide’s NVIDIA and PyTorch probes. Keep the untouched ZIP and private run directories outside the checkout. [Windows SSGD commands](fyp/training/SSGD_WINDOWS.md)
- **Approval and splits.** SSGD COCO crack/scratch mappings are imported as unverified source boxes. Confirm actual glass or phone identity and session evidence, resolve duplicate candidates, and use a second person to approve each selected image and its boxes or clean disposition. Published fold assignments alone cannot establish independent grouping. The existing split auditor and frozen-export preflight enforce those requirements. [Private review and export](fyp/BENCHMARK_HANDOFF.md)
- **Training.** The notebook, pinned initializations, resumable Drive outputs and matched evaluator are ready. The earlier one-epoch tests used generated software fixtures on CPU. Real SSGD training and accuracy results are pending. After approval and export, use an independent held-out collection and the same evaluator to compare candidates to the bundled detector. Run a short GPU smoke test if a suitable Windows training environment is available. Otherwise use private Drive and Colab T4 if academic terms permit that processing. Keep checkpoints in the private experiment directory. [Training and evaluation](fyp/training/README.md) · [Experiment record](fyp/experiment_log.csv)

## Files outside the Git transfer

No changed or non-ignored untracked files remained inside the cloud repository before the handoff commit. Ignored paths in the checkout were `.pytest_cache/`, `.revalue-runtime/` and Python `__pycache__/` directories. The following workspace files remain cloud-local or on the laptop. Recreate or copy only what you need through a private channel.

| Location | Contents and recovery |
| --- | --- |
| `/workspace/scratch/revalue-benchmark/` | Private Broken Interfaces pool with 95 real display crops, 10 reserved for blind practice, 85 author overlays, provenance CSV and audit/queue JSON. The last audit counted zero approved annotations. Recreate the pool from the pinned source and the benchmark handoff commands. |
| `/workspace/scratch/ReValue-Practice-*.html` | Private generated offline practice pages. Regenerate via the benchmark handoff when needed. |
| `/workspace/scratch/revalue-houdan-v1/` | External Houdan release asset, source checkout, probe script and private comparison previews and predictions. Use the official hash-checked download in the comparison tool to recover weights. |
| `/workspace/shared/downloads/ReValue-Redesign/`, `ReValue-V2/`, `ReValue-Qualitative-2026-11-20/` | Visual review bundles and qualitative exports. GitHub’s separate design branch also carries the desktop/mobile review sheets. |
| `/workspace/generated_images/`, `/workspace/attachments/`, `/workspace/scratch/revalue-fyp1-pr.md` | Design source images, supplied briefs and a draft PR note. |
| `/workspace/revalue-venv/`, `/workspace/revalue-runtime/` and temporary test/download files under `/tmp` | Linux dependencies, caches, reference checkouts and transient smoke outputs. Build a Windows environment from the pins. |
| `C:\Users\USER\Downloads\SSGD.zip` | User-supplied archive on the laptop. The local intake creates separate extracted and review copies. |

The bundled application checkpoint is tracked as `backend/models/revalue_exterior_yolo11n_v0.2.pt`. Checks in this handoff used the bundled model when exercising the normal app path. Keep any future experimental models separate from it.
