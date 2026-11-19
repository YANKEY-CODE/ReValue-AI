# ReValue AI — FYP1 development workspace

This workspace belongs to the **fyp1-development** branch. The original **main** branch was not changed.

## Historical baseline — NOT a new result
Source: `backend/models/MODEL_EVALUATION_v0.2.txt`

- 173 held-out images; 414 annotated instances (as reported, not independently audited)
- Overall precision 0.495; recall 0.486; mAP@50 0.426; mAP@50:95 0.181
- generic_crack precision 0.369; **recall 0.230**; mAP@50 0.215
- scratch precision 0.621; recall 0.743; mAP@50 0.637

The same YOLO weights and detector source are stored in the two existing ReValue AI repositories. We still need the original labelled test images and annotations to reproduce metrics.

## Run the existing application (on your laptop)
1. `git clone https://github.com/YANKEY-CODE/ReValue-AI.git`
2. `cd ReValue-AI`
3. `git switch fyp1-development`
4. `python -m venv .venv`
5. Activate the environment: Windows PowerShell .venv\Scripts\Activate.ps1, macOS/Linux `source .venv/bin/activate`
6. `pip install -r backend/requirements.txt pyyaml`
7. `python -m backend.src.server` then open http://127.0.0.1:8765
8. `python backend/tests/run_backend_self_test.py` and `python backend/tests/test_phase6a4_yolo_integration.py`

Do not commit credentials or unlicensed/private photographs.

## Prepare independent, labelled test data
Use smartphone crack/scratch images with YOLO detection labels and a dataset YAML specifying an independent `test:` split. Prefer phone- or photo-session-disjoint splits; check duplicate photos and labels. A test dataset has **not** been supplied or verified here.

## Reproduce the baseline
`python fyp/evaluate_detection.py --data /path/to/dataset.yaml --models backend/models/revalue_exterior_yolo11n_v0.2.pt --device cpu --output fyp/results`

Run additional detection weights with the SAME dataset, image size, and split. The script writes `summary.csv`, `per_class.csv`, plots, and run metadata.

Segmentation requires mask annotations and a separate segmentation evaluation (IoU/Dice); do not mix metrics as if they were the same task.

## FYP research focus
RQ1: Can alternate architectures or controlled data augmentation improve crack recall without excessive false positives?
RQ2: Do improvements transfer to different device models and difficult lighting conditions?

Log actual experiments, mistakes, data splits, inference latency, and supervisor feedback. The working branch starts from the earlier system but does not itself prove a new model improvement. If reusing another repository's contributions, confirm authorship, license, and permission first.
