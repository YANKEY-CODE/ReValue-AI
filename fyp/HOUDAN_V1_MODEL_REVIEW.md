# Houdan phone-defect-detection v1.0.0 review

19 November 2026. The [release](https://github.com/houdan-hub/phone-defect-detection/releases/tag/v1.0.0) supplies a four-class detector. The downloaded `best.pt` was kept in a separate experimental directory, `/workspace/scratch/revalue-houdan-v1/`. It is 19,156,634 bytes and matched the SHA-256 published alongside the GitHub release asset:

```text
c2c32004a2bbfae390fe439e01a1bdd00fed4ad21270b9cf2caedd5f0e0bf26c
```

## What is in the release checkpoint

- It is a standard Ultralytics YOLO11 **small** detection model. The loaded network reports scale `s`, config `yolo11s.yaml`, and 9,429,340 parameters. The training metadata names `yolo11s.pt`, image size 640 and Ultralytics 8.4.37. No CBAM module was present in the loaded network. These observations describe the checkpoint architecture and metadata, not a reproduction of its training.
- The release description, tagged training guide and model notes call it YOLO11n. The newer [training guide](https://github.com/houdan-hub/phone-defect-detection/blob/2d87cf0b04f38234f00fce2360786abf4c192d52/docs/training_guide.md) uses YOLO11s and agrees with the asset. The training repository also describes separate CBAM experiments, which should not be attributed to this checkpoint.
- The actual class IDs are `0 scratch`, `1 bump`, `2 paint`, and `3 crack`. A PyTorch forward pass with a `[1, 3, 640, 640]` RGB tensor returned a decoded detection tensor shaped `[1, 8, 8400]` before NMS: four box coordinates and four class scores, with no separate objectness channel. The Ultralytics prediction interface returned floating-point `[x1, y1, x2, y2, confidence, class_id]` rows in source-image pixel coordinates after NMS. The tagged model notes' 80-class ONNX example is not the measured PyTorch output. The separate ONNX asset was not tested.
- The checkpoint embeds `AGPL-3.0 (https://ultralytics.com/license)`. The project's [tagged LICENSE](https://github.com/houdan-hub/phone-defect-detection/blob/v1.0.0/LICENSE) notes that Ultralytics' base model is AGPL-3.0 and applies MIT to the project's custom training code, inference engine, grading and frontend. Review how AGPL applies to the intended integration and distribution before shipping this checkpoint. No downstream training-data reuse rights were established here.

The checksum was verified before reading the release checkpoint. The probe used PyTorch's `weights_only=True` restricted loader with an explicit list of standard PyTorch and Ultralytics classes. It did not execute the upstream project's training scripts. The loaded candidate used local Ultralytics 8.4.215 and PyTorch 2.15.0+cpu.

## Private qualitative comparison

Six display crops were selected at fixed sorted indices 4, 18, 33, 48, 63 and 78 (zero-based) from the 95 display crops in [Broken Interfaces](https://github.com/MHCI/broken-interfaces/tree/37877e61c93e17975a8a5968baefad3dba0b3231). These are photographs of smartphone displays showing the study's checkerboard test pattern. The authors release the dataset under CC BY 4.0 for research use. Attribution: Florian Schaub, Julian Seifert, Frank Honold, Michael Müller, Enrico Rukzio and Michael Weber, *Broken Display = Broken Interface? The Impact of Display Damage on Smartphone Interaction*, CHI 2014, [DOI 10.1145/2556288.2557067](https://doi.org/10.1145/2556288.2557067). This source has no verified ReValue-compatible two-class test annotations or independent split. It does not represent normal back or side captures and has no reviewed clean negatives.

Both models used the same EXIF-oriented images, 640-pixel square input, confidence 0.25, NMS IoU 0.70, FP32, batch 1 and CPU. Predictions were reviewed visually. The IDs below are local to this probe. Source photos, overlays and per-image prediction records were kept out of Git.

| Probe | Bundled YOLO11n | Houdan YOLO11s | Visual review |
| --- | --- | --- | --- |
| BI-01 | No boxes | No boxes | No clear crack at the review scale. This is not a verified clean negative. |
| BI-02 | No boxes | No boxes | Both missed apparent spiderweb damage along the left edge and lower-right area. |
| BI-03 | No boxes | One crack box at 0.289 | The box overlaps part of the visible crack network on the right half. Much of the network remains outside the box. |
| BI-04 | No boxes | No boxes | Both missed visible diagonal cracks across the lower half. |
| BI-05 | No boxes | No boxes | Both missed apparent branching damage on the bright, partly washed-out display. |
| BI-06 | No boxes | No boxes | Both missed apparent fine crossing cracks around the upper half and edges. |

No obvious false-positive box was observed on these six crops. There was only one prediction in total and no reviewed clean-negative set, so this cannot characterize false-positive rates, scratch performance or comparative accuracy.

Wall time was measured around warmed `YOLO.predict` on already decoded arrays, including preprocessing and postprocessing and excluding image loading and model initialization. The host used an Intel Xeon Platinum 8573C with OpenMP and MKL configured for two threads. Each model had three warm-up calls and three timed calls per image.

| Detector | Median warm prediction | Min–max | Timed calls |
| --- | ---: | ---: | ---: |
| Bundled ReValue YOLO11n | 88.1 ms | 61.7–367.8 ms | 18 |
| Houdan YOLO11s | 233.9 ms | 158.3–929.0 ms | 18 |

The spread is substantial. These are observations for this cloud session, not production latency estimates. No independent quantitative accuracy test ran. The upstream release metrics and ReValue's historical experiment numbers come from different, independently unverified evaluation setups.

## ReValue integration requirements

1. Keep the bundled model as the default. The candidate executes with the existing PyTorch and Ultralytics versions, and both models produce the same postprocessed box format. Keep checkpoint loading restricted and verify the pinned asset before use.
2. Add model-specific label normalization by name. The existing adapter recognizes `scratch` and `generic_crack`. A direct checkpoint swap would leave the candidate's `crack`, `bump`, and `paint` unresolved and could hold grading pending. Normalize `crack` to the generic crack signal before view-aware mapping. Keep bumps and paint-loss findings informational or pending review until there is a validated mapping to ReValue's taxonomy and grading rules.
3. Validate on one permitted, independent crack/scratch holdout shared by both models, with a known annotation policy and reviewed negatives. Keep native four-class results separate from the common-class comparison. Select thresholds on validation data and report crack misses, false positives, AP and latency on the held-out set. Rerun CPU timing with repeated, interleaved runs before setting a latency budget.
4. Test the model source and bounding box handling through the guided upload flow before any grading or valuation integration. Confirm licensing and provenance before distribution.
