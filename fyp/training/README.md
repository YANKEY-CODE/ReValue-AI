# Train the experimental smartphone detectors in Colab

[Open the training notebook in Google Colab](https://colab.research.google.com/github/YANKEY-CODE/ReValue-AI/blob/training/colab-yolo11/fyp/training/ReValue_Colab.ipynb)

[Prepare a downloaded official SSGD ZIP on Windows](SSGD_WINDOWS.md)

## Start here

1. Prepare an approved frozen export using the workflow below. Upload the **contents of the export** to a private `My Drive/ReValue-FYP/frozen/` folder. Its immediate children should include `manifest.json`, `images/` and `labels/`. A Roboflow ZIP or a folder of photos alone cannot be used here. Verify that the source terms and permissions cover research processing on your Google Drive and Colab account.
2. Open the notebook, or download the .ipynb from GitHub and use **File → Upload notebook** in Colab. Select **Runtime → Change runtime type → Python 3 → T4 GPU → Save**. Use the free allocation. If a GPU is unavailable, wait for your quota to renew. There is no need to buy compute units.
3. Use **Runtime → Run all**. Authorize the private Drive mount when prompted. The optional public-source intake switch defaults to False. Leave it off for an already prepared export. The training scripts and official initialization weights are pinned. The notebook keeps the Colab CUDA build of PyTorch and records runtime packages.
4. On disconnection, reconnect to the same accelerator type and rerun the notebook with the same Drive account and work directory. It verifies the data and completed weights before reuse. Use one session per work directory. A runtime or recipe change requires a new experiment directory. An interrupted run can resume from `weights/last.pt`. Retain periodic epoch files in case a write is interrupted. If the first checkpoint was never saved, archive that run and start fresh. Save sufficient Drive space for two runs, their periodic checkpoints, plots and initial weights.
5. Results go to `My Drive/ReValue-FYP/experiments/control-s17-v1/`. Each model has `weights/best.pt`, `weights/last.pt`, `results.csv`, `results.png` and validation confusion matrices. The last cell downloads an archive with both experimental best checkpoints and their recipe and checksum files. Only open checkpoints from a trusted source. Keep run plots, error examples and Drive contents private.

## Dataset intake and splitting

Use the existing private COCO, YOLO or Pascal VOC importer to preserve source IDs, terms, attribution, upstream splits and candidate boxes. Document case-by-case mappings to `generic_crack` and `scratch`. Retain the view metadata for front, back, camera and both sides. Uncertain or out-of-scope marks cannot establish an exhaustive target annotation or a reviewed clean phone. Follow the independent review, practice exclusion, provenance and duplicate workflow. [Private intake instructions](../BENCHMARK_HANDOFF.md)

Run the following commands from the repo root. Replace `/private/pool` and `/private/frozen` with paths outside the project. Use a fresh output folder. The proposal preserves existing assignments and uses a stable hash of connected physical-device and session groups for a nominal 70/15/15 allocation. Realized image counts vary. Practice-connected groups stay out. Assisted groups are training-only. Missing approvals and unknown identities stay in the pool. Test assignments require documented evidence of independence from the original checkpoint and pretraining sources. The planner cannot establish that evidence from pixels.

```bash
python fyp/training/split_plan.py /private/pool /private/proposed.csv
# Inspect the proposed CSV and group coverage before applying it.
python fyp/benchmark/dataset.py --root /private/pool apply-catalog /private/proposed.csv
python fyp/benchmark/dataset.py --root /private/pool audit
python fyp/benchmark/dataset.py --root /private/pool export /private/frozen
python fyp/training/pipeline.py prepare --dataset /private/frozen --work /private/preflight
```

The audit blocks exact duplicates, unresolved near duplicates and leakage. Keep one canonical image per duplicate and leave its copies in the pool. Exclude corrupt assets from intake and record the exclusions. Keep derivatives of a capture in the same device/session group. Review false near matches with a recorded reason. Do not reroll a split after seeing model outputs. If the proposed allocation lacks coverage, collect additional groups or document a group-stratified allocation before running inference.

The existing test gate requires at least 30 devices, 30 instances of each class and at least 15 devices each for crack, scratch and clean coverage. This pipeline also requires verified clean examples and both classes in training and validation. Training reads explicit approved image lists; a stray PNG cannot silently enter a split. [Dataset source and quality report](SOURCES.md)

## Experimental methodology

The bundled checkpoint is the fixed historical comparator. Its embedded training arguments specify 60 epochs, 640 px, batch 16, seed 42, optimizer auto, initial learning rate 0.01 and patience 15 under Ultralytics 8.4.142. These are saved arguments. The original training images, exact split membership and per-epoch log were unavailable here. The historical report uses 173 held-out images and 414 instances. Keep its 23.0% crack recall and 74.3% scratch recall in the historical record. [Bundled evaluation report](../../backend/models/MODEL_EVALUATION_v0.2.txt)

Validate the original detector on the approved validation split before fitting. Train experimental YOLO11n and YOLO11s from official Ultralytics COCO weights, using identical data and the existing 100-epoch control recipe at 640 px, seed 17, batch 8 and AdamW. Record the code revision, environment, dataset manifest hash, initialization hashes and resulting checkpoint hashes. Select the best epoch using validation fitness. These controls compare two model sizes on the new corpus and do not reproduce the historical training run.

Evaluate all three checkpoints against the same independently labelled test images in a single run. Compute per-class precision, recall, F1, FP, FN and FP on clean examples at confidence 0.25, matching same-class boxes one-to-one at IoU 0.50. Compute per-class AP and macro mAP at IoU 0.50 and 0.50–0.95 from predictions down to confidence 0.001. Use NMS IoU 0.70, square 640 input and FP32. Time the CPU predict call with batch one and two threads, excluding disk decode, after three warmups per model. Rotate model order by image. The median and p95 include preprocessing and NMS at the AP score floor. CPU timing is machine-specific.

Read `final-test/per_class.csv`, `summary.json` and `private_errors.json` together. Review missed fine cracks at original resolution and check false alarms on reflections, edge seams and screen protectors. Review difficult strata only where actual view or severity metadata supports them. Choose the operating point and acceptable false-positive cost on validation before opening test results. A single training seed limits conclusions about variability. Further seeds, 960 px inputs and modest photo augmentation are separate, predeclared ablations. Repeated tuning after examining the test requires a fresh independent holdout. [Experiment protocol](../EVALUATION_PROTOCOL.md)

## Verification

On CPU-only Linux, 12 pipeline, benchmark and evaluation unit tests passed. Both official COCO initializations were downloaded from the tagged release, checksummed and loaded. A one-epoch, 64 px synthetic smoke fit of each architecture produced last/best weights, training curves and validation confusion matrices. The matched evaluator exercised all three checkpoints on synthetic fixtures. The temporary outputs were discarded. Google Drive mounting, free GPU availability and training on a real reviewed dataset still require a Colab run. No new accuracy figures were recorded.
