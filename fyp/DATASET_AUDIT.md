# Candidate datasets for the YOLO11n baseline

Audit date: 19 November 2026. No candidate was cleared for quantitative two-class evaluation. The historical 173-image, 414-instance test set and the checkpoint's training membership are not included in the project. Results on a separately sourced test set would be an external benchmark. Reproducing the historical test requires its original images, labels, split provenance and evaluation settings.

| Source | Download and terms | Labels and split | Decision |
| --- | --- | --- | --- |
| [Roboflow Mobile Damage Diagnosis](https://universe.roboflow.com/vikass-workspace-pmumc/mobile-damage-diagnosis-czt4o) | The cloud proxy rejected the HTTPS tunnel with 403 before the Universe site responded. API and app hosts were blocked too. Project availability, version, export format, and licence are unverified. | Labels, image quality, duplicates and split provenance could not be inspected. | Obtain an authorized versioned YOLO detection export and the dataset card, including the reuse terms and image provenance. |
| [SSGD](https://github.com/VincentHancoder/SSGD/tree/2004178e4ff0cb61787e4940b871f1e5e2645c29) | Git source accessible. The README permits academic use only for the dataset. Apache 2.0 is the repository's code licence. Both Tsinghua Cloud links and the Baidu link were blocked by the cloud proxy before the origin responded. | The README reports 2,504 images, 3,914 defects, and seven classes: crack, broken, spot, scratch, light leakage, blot, and broken membrane. The loader expects COCO boxes, with no YOLO export in Git. It includes five-fold configurations for LB101 and LB201, but every configuration points both validation and test to the same fold JSON. The split helper stratifies individual images without grouping by physical device or session. | Promising for screen glass. Obtain the archive, verify image quality and group independence, convert crack and scratch boxes by category name, and explicitly resolve how other classes are treated. Avoid silently treating other damage as clean negatives. |
| [Broken Interfaces](https://github.com/MHCI/broken-interfaces/tree/37877e61c93e17975a8a5968baefad3dba0b3231) | Git download succeeded. The README grants CC BY 4.0 for the dataset and asks researchers to credit the CHI 2014 paper. The audit did not use the survey responses. | Participant photos and registered display variants with manual SVG damage markings. No published YOLO boxes, crack/scratch class mapping or split manifest found. See the image audit below. | Useful as a front-display annotation source after manual relabelling and grouping. It cannot supply two-class metrics as released, and it does not represent rear or side damage. |

## Broken Interfaces image audit

The checkout contains 95 originals, 95 display crops, 95 overlays and 95 SVG annotations. The original set comprises 94 JPEG/PNG files and one single-frame GIF (1224 × 1632). The JPEG/PNG files in all three folders decoded successfully, and all SVGs parsed. Each original filename stem matches a crop, overlay and SVG. The SVGs contain paths and rectangles, but their element metadata did not expose a crack/scratch class scheme.

| Images audited | Short edge, min / median / max | Below 640 px | Below 960 px |
| --- | --- | ---: | ---: |
| 94 JPEG/PNG originals | 189 / 1,920 / 3,456 px | 13 | 22 |
| 95 display crops | 136 / 984 / 2,024 px | 28 | 47 |
| 95 overlays | 136 / 984 / 2,024 px | 28 | 47 |

No within-folder JPEG/PNG duplicates were flagged by file SHA-256 or by SHA-256 of EXIF-oriented RGB pixels. A near-duplicate screen also flagged zero within-folder pairs using an aspect ratio within 10%, DCT perceptual hash distance at most six and difference-hash distance at most six. This is a screening result, and the original GIF was outside the duplicate scan. Automated quality checks covered decoding, dimensions and coarse brightness. One JPEG/PNG original had mean grayscale intensity below 40 of 255, and one crop exceeded 215. Blur, glare and whether individual cracks are visible still require review before using the data for detection.

The crops, overlays and SVGs are derived from the originals and must be grouped with them, never counted as independent photos or distributed across splits. An image-level duplicate scan does not identify different photos of the same phone. Before building a split, group by physical phone and capture session where known, verify derivative associations, review near duplicates and label crack/scratch instances exhaustively. A damage-only corpus does not supply reviewed clean negatives.

## Baseline gate

1. Obtain a versioned, permitted archive and document the terms alongside its source. Keep archives, labels, and individual review examples outside Git.
2. Check decodability, resolution, blur, glare and framing, along with box alignment, class mapping, and negative coverage. Audit exact and near duplicates within and across splits and check overlap against the checkpoint training set. Split by phone or capture session before running the model. Where training provenance is missing, report that the run's independence cannot be established.
3. Freeze the same held-out set for 640 and 960 pixels. Follow [the evaluation commands](README.md#run-a-held-out-detection-comparison) with the bundled YOLO11n weights, confidence 0.25 and IoU 0.50 for operating-point metrics. Report per-class precision, recall, F1, AP at IoU 0.50 and AP across IoU 0.50–0.95, aggregate mAP, and FP/FN counts. Review missed cracks on the same images at both resolutions with source images kept private.
4. Record any measured results separately from [the historical experiment record](experiment_log.csv). Defer alternative model training until the baseline is validated.

## Access recheck and private intake

The cloud proxy still blocks the named Roboflow workspace, both SSGD archive hosts, and dataset search endpoints on Zenodo and Hugging Face. These are connectivity results, so no inference about whether those sources have an eligible export is possible. Broken Interfaces remains accessible at its pinned revision under CC BY 4.0 for research use. The practice images are display crops, and the cloud pool remains unapproved with no eligible splits.

For a legitimately acquired archive with written reuse terms, [the intake guide](BENCHMARK_HANDOFF.md#accepting-a-new-authorized-dataset) describes private COCO, YOLO and Pascal VOC imports. Published splits are retained as provenance only. They are not evidence of device or session independence.
