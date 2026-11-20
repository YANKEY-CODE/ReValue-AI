# Prepare the official SSGD ZIP on Windows

Use the original archive at `C:\Users\USER\Downloads\SSGD.zip`. SSGD's authors permit **academic use only**. Cite Haonan Han, Rui Yang, Shuyan Li, Runze Hu and Xiu Li, *SSGD: A Smartphone Screen Glass Dataset for Defect Detection*, ICASSP 2023. The authors report 2,504 images and 3,914 defects across seven categories. Your archive's inventory below is authoritative for this run. [Official release and use terms](https://github.com/VincentHancoder/SSGD/tree/2004178e4ff0cb61787e4940b871f1e5e2645c29)

## Run the private intake

Open PowerShell on the laptop. The commands preserve your existing checkout by attaching the fetched training revision in a separate worktree. Set `$tools` to a fresh path if you already have a worktree there. Reuse the installed ReValue Python environment. Check the output after each command.

```powershell
$repo = 'C:\Users\USER\ReValue-AI'
$zip = 'C:\Users\USER\Downloads\SSGD.zip'
$tools = Join-Path $env:USERPROFILE 'ReValue-SSGD-tools'
$private = Join-Path $env:LOCALAPPDATA 'ReValue-SSGD'
$python = Join-Path $repo '.venv\Scripts\python.exe'

git -C $repo status --short --branch
if (!(Test-Path -LiteralPath $zip -PathType Leaf)) { throw "Missing SSGD archive at $zip" }
if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw "ReValue Python environment is missing. Follow WINDOWS_SETUP.md first." }
git -C $repo fetch origin training/colab-yolo11
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed' }
git -C $repo worktree add --detach $tools FETCH_HEAD
if ($LASTEXITCODE -ne 0) { throw 'Worktree setup failed. Choose a fresh tools path if it already exists.' }

& $python (Join-Path $tools 'fyp\training\prepare_ssgd.py') --archive $zip --output-parent $private --permission-ref 'Official SSGD author download, academic-use terms'
```

The command prints the **Private intake directory**. Each invocation uses a fresh directory under `$private`. It verifies Windows-safe ZIP paths, extracts the archive there, reads COCO fold 1 from each recognized subset, and imports valid image/annotation pairs into the existing review pool. The other folds reuse images, so their rows are not added to these counts. Source train and validation names are recorded as provenance. A hash of the ZIP identifies the input version. Imported references map only `crack` and `scratch` to ReValue classes. Other boxes retain their original names. The raw archive stays available for diagnosis.

- `intake.json` contains counts for actual image files, fold 1 image paths, COCO rows, unique path/class/box signatures, declared classes, valid target references and any skipped assets.
- `audit.json` contains exact and near-duplicate candidates, including any overlap between supplied folds, and split gate results.
- `provenance.csv` and `review-queue.json` identify what needs evidence or approval. The private `pool/source_references/` contains mapped COCO boxes as pixel coordinates for review.
- `error.json` records an unreadable archive or layout error. An intake that exits nonzero with an `intake.json` has a partial review pool. Inspect reported errors before proceeding.

## Review and assign groups

Open the local annotator using the private directory printed during intake.

```powershell
$run = Read-Host 'Paste the Private intake directory printed above'
$pool = Join-Path $run 'pool'
& $python (Join-Path $tools 'fyp\benchmark\annotate.py') --root $pool
```

Open [the local annotator](http://127.0.0.1:8769). Use source-reference boxes to locate candidates. Read the original pixels and check every box and clean decision before submitting. A second person must verify every selected image. Use author or capture records to establish phone/glass identity and session grouping in `provenance.csv`. Keep assets of unknown provenance in the pool. Published SSGD fold assignments alone are insufficient to establish independence. The upstream configurations point validation and test to the same JSON, so use a separate independently proven test collection for the Colab benchmark. Inspect the duplicate report, use one canonical copy per duplicate, and record the rationale for any reviewed false match.

After approvals and provenance, use the existing [split planning, audit and export instructions](README.md#dataset-intake-and-splitting). The planner proposes groups from verified identities and the frozen benchmark gate checks the final split. An export with inadequate test coverage cannot run through the training pipeline preflight. Never assign groups based only on filenames or assume that unlabelled and out-of-scope defects are clean.

## Check the laptop GPU and run local tests

```powershell
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { nvidia-smi -L }
& $python -c "import torch; print('PyTorch:', torch.__version__, '| CUDA build:', torch.version.cuda, '| CUDA available:', torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'No CUDA device accessible to this environment')"

$env:PYTHONPATH = "$(Join-Path $tools 'fyp\training');$(Join-Path $tools 'fyp\benchmark');$(Join-Path $tools 'fyp')"
& $python -m unittest test_prepare_ssgd test_pipeline test_benchmark test_import_practice test_evaluate_detection
```

An NVIDIA adapter may exist even when the Windows app's CPU build of PyTorch reports CUDA unavailable. A local GPU smoke run needs a separate CUDA-enabled training environment and an approved split. Keep the app environment and training outputs separate. Use a new experiment folder for any short GPU smoke run. If this environment is CPU-only, use Colab after review.

## Move the approved dataset to Colab

1. Run the existing export and preflight on the approved collection. The export directory has `manifest.json`, `images/`, `labels/` and `data.yaml`.
2. Once the academic permission covers private Drive/Colab processing, place those contents directly in the private **My Drive → ReValue-FYP → frozen** folder. Keep the source ZIP, review fragments and raw pool local.
3. Open the [ReValue Colab notebook](https://colab.research.google.com/github/YANKEY-CODE/ReValue-AI/blob/training/colab-yolo11/fyp/training/ReValue_Colab.ipynb). Choose **Runtime → Change runtime type → T4 GPU → Save**, then **Runtime → Run all** and authorize the private Drive mount.
4. For a new experiment, use a fresh experiment directory in the Drive cell if `control-s17-v1` already has results. Experimental weights are saved in that experiment directory. [Full training and resume guide](README.md)
