# FYP1 detection evaluation protocol

**Question.** Can higher resolution, a different detector, or controlled augmentation improve crack recall without increasing false positives beyond an acceptable level? Can the chosen configuration generalize to different phones and lighting conditions?

1. Obtain the original held-out 173 images and YOLO box annotations if available, plus dataset provenance, permissions, training/validation membership and original evaluation settings. For an independent dataset, record the annotation guidelines, capture sessions, physical phones, device families and image conditions. Include reviewed clean negatives, including reflections, seams, fingerprints, dust and screen protectors. Annotate cracks and scratches consistently and record ambiguous cases for adjudication. Keep private assets and subject identifiers outside Git.
2. Split by physical phone and capture session before training. Use near-duplicate checks and review photos that appear in more than one source. Record dataset version and counts per class and view. Hold out difficult examples without selecting them based on model outputs. Tune confidence and other settings on validation data only, and freeze them before opening test metrics. The evaluator defaults to the app's 0.25 confidence for an operational comparison. Report any additional validation-selected operating points separately.
3. Compare the bundled YOLO11n checkpoint at 640 and 960 first. The historical weights may have seen overlapping data until provenance is established, so treat results as an independent comparison only after verifying separation. For model comparisons train YOLO11n and YOLO11s on identical splits, initialization policies and budgets. RT-DETR-L is a separate architecture candidate when hardware permits. Use the same class mapping, target input resolution, evaluation images, confidence rule, hardware, precision, batch size and software versions. Report parameter count and practical CPU cost. Document any architecture-specific postprocessing and preprocessing.
4. Run augmentation ablations with the architecture and training budget fixed. Start with an unaugmented control, then test realistic brightness/contrast and modest scale and translation. Verify that boxes remain meaningful and fine cracks are still visible. Avoid augmenting validation and test data. Compare paired runs with the same seeds and report their variation. Tiling can be a later ablation if resizing erases thin cracks. Record tile size and overlap, transform boxes back to source coordinates, deduplicate predictions and include the extra compute in latency.
5. Report precision, recall, F1, mAP@50 and mAP@50–95 with crack and scratch breakdowns. Include crack FP on all photos and per reviewed negative image, as well as crack misses by view, lighting and device. Select a rule for acceptable FP and latency on validation data before running final tests. For robust latency, warm up each model, use the same device and thread count, repeat runs, and report median and spread. For statistical uncertainty, bootstrap by physical phone or session when sample size permits. The evaluator records per-pass mean timing and counts. Subgroup analysis and uncertainty intervals require additional dataset metadata.
6. Keep segmentation separate if mask annotations become available. Record annotation quality, mask IoU/Dice and latency on a separate split and ask a distinct research question about localization of thin defects. Bounding boxes cannot serve as mask ground truth.

## Reproducible training recipe

The commands below are prepared for use after data, trusted pretrained weights and hardware are available. They have not been run. Use the same `data.yaml`, seeds, batch and training budget for each YOLO model. `device=0` assumes a CUDA environment with separately recorded versions and drivers.

```bash
yolo detect train model=/path/to/yolo11n.pt data=/path/to/data.yaml \
  imgsz=640 epochs=100 batch=8 device=0 seed=17 deterministic=True \
  optimizer=AdamW lr0=0.001 patience=100 \
  cfg=fyp/training-control.yaml project=fyp/training-runs name=yolo11n-control-s17

yolo detect train model=/path/to/yolo11n.pt data=/path/to/data.yaml \
  imgsz=640 epochs=100 batch=8 device=0 seed=17 deterministic=True \
  optimizer=AdamW lr0=0.001 patience=100 \
  cfg=fyp/training-control.yaml hsv_v=0.15 translate=0.04 scale=0.10 \
  project=fyp/training-runs name=yolo11n-photo-augmentation-s17
```

Repeat with preregistered seeds and with YOLO11s for the size comparison. Verify effective config in each run's `args.yaml`, record the pretrained weight hash, and select a checkpoint and threshold using validation only. Use new output directories for each trial. Run the held-out evaluator with the chosen checkpoints and add each real completed run to [experiment_log.csv](experiment_log.csv) with its manifest path. Keep software fixture results out of the experiment log.
