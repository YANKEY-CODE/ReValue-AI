# ReValue FYP1 real-image benchmark

The private workspace currently holds **95 unlabelled Broken Interfaces display crops**. The provenance audit found 28 with a short edge below 640 pixels and flagged no exact or near-duplicate pairs at the configured thresholds. This check cannot identify all repeated devices, crops or sessions. Ten crops are reserved for practice, with separate unlabelled copies for each annotator. There are **zero approved annotations and zero verified train, validation or test images**. No model accuracy metrics were generated.

## Annotation protocol

| Disposition | Decision rule |
| --- | --- |
| `generic_crack` | A visible fracture in the surface, such as an irregular branching line or a spiderweb radiating from an impact. Draw a tight rectangle around each connected crack network or clearly separate crack. A single rectangle can span a connected network. Do not draw a separate box for each branch. |
| `scratch` | A visible surface abrasion or scuff line whose bounds can be distinguished from a fracture. Box each distinguishable continuous scratch. For tightly clustered scratches, use separate boxes where distinguishable and exclude the image for adjudication if the targets cannot be marked consistently. |
| Verified clean | Inspect the entire in-scope surface at 100% and zoom as needed. Adequate framing, focus and lighting must let you rule out visible damage on that surface. Record which surface you checked. A blank annotation is valid only after a human explicitly marks it clean and a second human approves it. Clean describes the pictured surface, not the whole device. |
| Exclude | Use for cropped-off or obscured damage, a hard-to-read surface, a visible mark that reviewers cannot distinguish from glare, wallpaper, a screen protector, dirt or a seam, or a view dominated by other damage with uncertain coverage. State the reason. Do not use bump/paint-only or unevaluable photos as clean negatives. |

Draw tight axis-aligned boxes in upright, original-resolution coordinates. Include the visible mark with minimal margin and leave unrelated regions out. Label both classes when present. Use the same connected-network convention across all images. Keep validation, test, practice and independent review blind to model outputs. Only train-assigned photos may use the optional proposal workflow below. Broken Interfaces SVGs may be consulted in a separate second pass to locate markings, but neither SVG path geometry nor color establishes a crack or scratch label. Require reviewers to confirm the source pixels and resolve discrepancies.

## Manual work required

1. **Confirm sources and capture fresh photos.** The imported legacy crops are good for calibrating annotation rules. Their published pairing stems identify derivatives of each image, and do not establish physical device or session independence. Leave those records in `pool` unless you can establish that provenance and rule out training overlap for both checkpoints. For an independent test set, capture new photos with consent after recording the frozen checkpoint hashes. Record a capture date, stable pseudonymous physical-device ID and session ID. Keep the same IDs for repeated shots. Cover front, back and accessible side views, with realistic lighting and reviewed clean surfaces. Remove identifying content before intake. Document any permitted source terms and how the images were modified.
2. **Calibrate with your reviewer.** Each person independently annotates the same 10 practice images before looking at the other person's boxes. Compare class, box extent, connected cracks and clean decisions. Agree on the rules and document disagreements. Use the separate practice workspaces below. The split auditor excludes the reserved originals, their exact duplicates, unresolved near matches, and any known shared phone or session. Then draw boxes or mark **Verified clean** or **Exclude** for every eligible image you want to use, with a note. Have a second person open **Review**, use their own ID, check the entire image and approve or request revision. If you edit a submission, it needs approval again. Do not enter a second ID yourself to stand in for a reviewer.
3. **Apply provenance and preassign splits.** In the private CSV fill in `device`, `session`, and `split` with `train`, `val`, `test`, or `pool`. Use unique device IDs across the full collection, with the same ID for the same physical phone even across sources. Keep a device and all its sessions in one split. For every test photo, fill `overlap_evidence` with a private record reference that verifies separation from both checkpoint training corpora, such as consented original capture dated after the checkpoint artifacts were frozen. Use the optional `capture_date` and `permission_ref` columns for the documented date and consent or licence record. Leave unknown values blank and keep unverified records in the pool. Keep training candidates and calibration photos separate and do not train a model during this audit.
4. **Collect enough holdout data.** The tool's exploratory minimum is 30 physical devices, at least 30 instances of each class, and each class and verified clean surfaces represented on at least 15 devices each. Those requirements are simultaneous. More devices may be needed, especially if damaged and clean examples are mostly on different phones. These are collection gates, not statistical power guarantees. Plan more observations for narrow confidence intervals or subgroup claims. Keep the holdout blind until labels, thresholds and membership are frozen.
5. **Resolve flagged duplicates.** Check the private audit along with framing, blur and glare. Exclude repeated or derivative images rather than counting them as independent examples. For a near-hash match that a reviewer verifies is distinct, record an explanation and reviewer ID in `duplicate_reviews.json` in the workspace, as a JSON map from the audit pair key `a:b` to a rationale string. Exact duplicates cannot be waived. The hash screen does not replace device- and session-level review.

## Run the workflow

From the repository root with the [FYP Python environment](README.md#reproducible-development-setup) active, set `BENCHMARK` to a dedicated private directory outside Git. The cloud copy is ready at `/workspace/scratch/revalue-benchmark`. To recreate it locally, clone the authorized Broken Interfaces source outside this checkout and pass the checkout at revision `37877e61c93e17975a8a5968baefad3dba0b3231` to `import-broken`. The importer verifies the revision and crop bytes, stores attribution and both source and normalized hashes, and strips metadata by re-encoding upright pixels in PNG. It does not import survey responses, SVGs, overlays or originals.

```bash
umask 077
BENCHMARK=/workspace/scratch/revalue-benchmark
# For a fresh private workspace only:
# python fyp/benchmark/dataset.py --root "$BENCHMARK" import-broken /private/broken-interfaces

python fyp/benchmark/dataset.py --root "$BENCHMARK" add /private/my-photo.jpg \
  --source consented-fyp-captures --asset capture-001 --view front \
  --license 'Permission for private FYP evaluation; evidence consent-001' --attribution 'FYP participant, pseudonym P01'

python fyp/benchmark/annotate.py --root "$BENCHMARK"
```

Open `http://127.0.0.1:8769` in a browser on the same machine as the command. Work on the private machine with your reviewer, or hand off the private workspace securely and resume after their review. Use two separate people and pseudonymous IDs. The server is loopback-only and there is no account system or hosted preview.

For the initial blind practice, use these commands in two terminals. The cloud practice folders are already prepared. On a fresh import, run the commented preparation command once.

```bash
BENCHMARK=/workspace/scratch/revalue-benchmark
# python fyp/benchmark/dataset.py --root "$BENCHMARK" prepare-practice
# Terminal A:
python fyp/benchmark/annotate.py --root "$BENCHMARK/practice/annotator-a" --port 8770
# Terminal B:
python fyp/benchmark/annotate.py --root "$BENCHMARK/practice/annotator-b" --port 8771
```

Each annotator uses their own localhost port to label all ten IDs without opening the other workspace. Compare the saved boxes and notes by matching image ID after both have finished. Record any rule changes before returning to the main workspace. Practice labels are never transferred into the benchmark.

To see exactly who acts next, generate the private work list:

```bash
python fyp/benchmark/dataset.py --root "$BENCHMARK" queue > "$BENCHMARK/next-actions.json"
```

- `practice`: both people annotate all ten matching IDs in their own queues.
- `check_provenance`: you document rights, device/session and split eligibility. Leave unverified photos in the pool.
- `annotate` and `revise`: you draw or correct the human labels.
- `independent_review`: the second person checks the full photo and current submission. Any later edit requires approval again.
- `approved`: human review is recorded against the exact annotation content. Split eligibility still requires the audit.

Optional proposals are limited to authorized photos already assigned to **training**, with known device and session. With the annotator stopped, run the following using an ID from your private catalogue:

```bash
python fyp/benchmark/propose.py --root "$BENCHMARK" <TRAIN_IMAGE_ID>
```

In Annotate mode, inspect the full photo first, then optionally choose **Inspect training proposals**. Add individual boxes to the draft only after checking the pixels, and draw any missed marks. The detector cannot submit a label, approve it, or mark an image clean. Proposal boxes and scores are hidden in Review mode. Proposal generation writes private sidecars and marks the source photos as model-assisted. The audit blocks them, matched duplicates and known phone/session relatives from validation and test. Do not generate proposals for blind practice or held-out candidates.

After annotation, stop the server before editing provenance or freezing a dataset. The catalog command regenerates the CSV from stored values, so save edits before rerunning it.

```bash
python fyp/benchmark/dataset.py --root "$BENCHMARK" catalog > "$BENCHMARK/provenance.csv"
# Edit the provenance columns in the CSV, then:
python fyp/benchmark/dataset.py --root "$BENCHMARK" apply-catalog "$BENCHMARK/provenance.csv"
python fyp/benchmark/dataset.py --root "$BENCHMARK" audit > "$BENCHMARK/audit.json"
python fyp/benchmark/dataset.py --root "$BENCHMARK" export "$BENCHMARK/frozen-v1"
```

Export writes a private JSON split manifest with provenance, normalized images and YOLO labels, and explicit empty labels for approved negatives. It accepts only approved, selected rows that pass split checks. It can freeze a small development subset, but the evaluator refuses a snapshot whose test set fails the collection minimum. The JSON state includes source attribution and reviewer notes, so keep it private too.

Once all test blockers are clear, run the experimental evaluation:

```bash
export YOLO_CONFIG_DIR="$PWD/.revalue-runtime/yolo" MPLCONFIGDIR="$PWD/.revalue-runtime/matplotlib"
export OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 YOLO_AUTOINSTALL=false
for SIZE in 640 960; do
  python fyp/benchmark/evaluate.py \
    --dataset "$BENCHMARK/frozen-v1" --imgsz "$SIZE" \
    --houdan /workspace/scratch/revalue-houdan-v1/best.pt \
    --output "$BENCHMARK/results-v1-$SIZE"
done
```

The evaluator rechecks eligibility from the frozen rows, their human approval hashes, split membership, YOLO label contents, and both checkpoint hashes. Each run compares batch-one, square FP32 inputs at the requested size on CPU using the same NMS settings. Check that both resolution reports contain the same dataset manifest SHA-256. Operating-point metrics and private FP/FN cases use confidence 0.25 and class-aware IoU 0.50. Report per-class precision, recall, F1, AP@50, AP@50–95, FP and FN, with aggregate mAP and warm CPU median/p95 latency. AP uses ranked outputs with a 0.001 confidence floor. The report counts native `bump` and `paint` predictions separately and does not grade them. Houdan's `crack` is mapped to the common class **only inside this evaluator**. Review missed-detection examples privately using the opaque IDs and coordinates after the run, then report only permitted aggregate results.

Broken Interfaces reuse is covered by CC BY 4.0 with author attribution, and the derived normalized images retain provenance in private records. Houdan's checkpoint declares AGPL-3.0, which requires review before integration or distribution. ReValue's default checkpoint and application grading are outside this experiment.

Run software verification with `python fyp/benchmark/test_benchmark.py`. The [experiment log](experiment_log.csv) distinguishes the blocked benchmark from historical metrics.

## Offline label exchange

Download the HTML package for your assigned role to a personal browser. It includes your queue's ten cropped photos with CC BY 4.0 attribution. Save each annotation and use **Download my labels** to create a backup. Use **Import saved labels** to resume from a backup or move browsers. Use separate packages and browser profiles for the two people. Do not open the other package before finishing. The files contain private practice work and belong outside Git.

From the repository root, prepare fresh files or import completed submissions while the annotator is stopped:

```bash
python fyp/benchmark/practice.py --root "$BENCHMARK" package annotator-a /private/ReValue-Practice-A.html
python fyp/benchmark/practice.py --root "$BENCHMARK" package annotator-b /private/ReValue-Practice-B.html
python fyp/benchmark/practice.py --root "$BENCHMARK" import /private/revalue-practice-a-labels.json
python fyp/benchmark/practice.py --root "$BENCHMARK" import /private/revalue-practice-b-labels.json
python fyp/benchmark/practice.py --root "$BENCHMARK" compare "$BENCHMARK/practice-review.md"
```

The report matches boxes one to one by overlap and identifies missed, extra, differently named and poorly aligned boxes, plus differences in clean/positive/excluded decisions. An overlapping pair with the same class counts as a match at IoU ≥ 0.50. Use this report as an agenda for human calibration. Distinct IDs are a consistency check, not proof of authorship. A conflict with existing saved work halts import instead of overwriting it.

## Accepting a new authorized dataset

Supply a source directory outside the benchmark and checkout, the actual rights and source version, and explicit source-class mappings. For example, if a licensed COCO archive becomes available:

```bash
python fyp/benchmark/import_dataset.py --root "$BENCHMARK" \
  --source-root /private/authorized-export --format coco \
  --annotations annotations.json --images images --upstream-split supplied_test \
  --source 'official source URL or name' --version release-id \
  --license 'exact reuse terms' --attribution 'credited authors' --permission-ref 'private evidence ID' \
  --map crack=generic_crack --map scratch=scratch --report "$BENCHMARK/coco-intake.json"
```

For YOLO use `--format yolo --annotations data.yaml --upstream-split test` and image-directory splits declared in the YAML. For Pascal VOC use `--format voc --images JPEGImages --annotations Annotations` with standard one-based inclusive boxes. Import each supplied split separately and audit after intake. Move no data based on the upstream split alone. Orientation must already be normalized with the labels. The tool skips corrupt images or invalid annotations, records the issues privately, and returns a nonzero exit if any were skipped. All records start in `pool`; mapped boxes live in `source_references/` and never populate human labels or reviews. Broken Interfaces SVG display markings retain their original interpretation and are not converted to crack/scratch ground truth.
