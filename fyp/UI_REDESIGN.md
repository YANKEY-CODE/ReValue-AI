# ReValue UI redesign V2

[Desktop before and after](design-review/desktop.jpg) · [Mobile before and after](design-review/mobile.jpg)

## Design and implementation

The starting point for V2 was `602828c` on `fyp1-development`. The previous screen used the same bordered container for the introduction, instructions and controls. On wide screens, the capture heading and the five-photo strip followed different alignment guides. The catalogue and report also used nearly the same visual hierarchy despite supporting different decisions.

Two concepts were explored with an image-based design board. The editorial inspection manual pairs a large serif headline, an original studio illustration and a ruled sequence of instructions. A charcoal instrument-panel concept gave photos a strong frame but made long evidence notes harder to scan. The implementation uses the editorial layout for guided assessment and reports, with a dark viewing surface for qualitative comparisons.

- Shared offline tokens and control styles live in `app/revalue-design.css`. Main-app layouts live in `app/revalue-professional.css`. The original demo and component geometry now loads first from `app/revalue-legacy.css`. The supervisor asset allowlist and Docker build context include that file.
- The desktop assessment places device and progress information beside the active task. On small screens these read in sequence. Catalogue shortcuts expose their selection to assistive technology. Camera-angle diagrams distinguish the five required views before upload and give way to actual previews.
- The report puts the exterior grade, detector evidence and MYR status alongside the user's quote calculator on desktop. When the backend returns candidates, the report identifies each view, class and model score. Existing grading, receipts and evidence eligibility determine what can be shown.
- The local comparison workbench separates upload, run settings, original photo and detector outputs. In the enlarged view, **Show boxes** lets a reviewer inspect the same pixels at the same zoom level. Reopening the inspector restores the overlays.
- The three requested skill guides were read from their official source checkouts. The design uses the UI UX Pro Max guidance on legibility and touch controls, Frontend Design's viewport review, and Frontend App Builder's concept-to-browser comparison. Runtime assets are local.

## First redesign history

The assessment page used several layers of dark, animated styling over a narrow mobile-first layout. Device setup left search failures looking like empty results. Photo requirements were hard to scan and errors could disappear before the user fixed them. The report put evidence status below prominent price styling, while the separate comparison page used its own visual system.

- The first redesign introduced shared offline typography, emerald accents, surfaces, buttons and keyboard focus styles. The assessment landing page explains the live and demo options and uses an illustrative studio image.
- The assessment separates device search, storage confirmation and the five photo views. It labels the required views, previews selected images, keeps their validation messages beside the affected slot, and distinguishes file selection from camera capture. QR capture uses the same styling.
- The analysis screen identifies the detector, shows candidate confidence and uncertainty, and preserves the existing review gate and provisional grade behaviour. The report distinguishes an evidence-based estimate, a lack of eligible evidence, a failed market request and illustrative demo values. It includes a print layout and the existing MYR quote calculator.
- The experimental comparison adds a removable file queue, drag-and-drop, batch progress, a box legend, and keyboard-accessible zoom. Exports and comparison parameters use the existing schema and settings. Accuracy still requires verified annotations.

## Windows launch

Use the existing project checkout and environment. Open PowerShell in the project directory and update the branch.

```powershell
Set-Location 'C:\Users\USER\ReValue-AI'
git fetch origin
git switch design/revalue-premium-v2
git pull --ff-only origin design/revalue-premium-v2
```

Run the assessment in one PowerShell window and the comparison in a second window from the same directory. Leave each process running while using its site.

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-revalue.ps1
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\compare-models.ps1
```

The assessment opens at [127.0.0.1:8765](http://127.0.0.1:8765) and the comparison at [127.0.0.1:8766](http://127.0.0.1:8766).

## V2 verification

- Chromium on Linux exercised catalogue validation and filtering, device storage, five validated images, scan failure and review-required fixtures, real YOLO11n CPU inference, QR capture, quotes, a live report and the print stylesheet. Chromium printed the fixture-based real-inference report to a one-page A4 PDF.
- The comparison smoke exercised real CPU predictions and both downloads. Controlled output fixtures covered bounding-box position and class labels, hiding boxes, restoring them, zoom, dialog focus and CSV escaping.
- The local Docker build used the cloud proxy CA as a transient BuildKit secret during dependency installation. The container included the additional stylesheet. Running the same supervisor smoke directly and through a local TLS proxy to that container checked anonymous denial, authenticated access, sanitized uploads, real inference and reports on desktop and an emulated phone. Windows, physical camera hardware and public hosting were outside these checks.
- The backend suite passed 69 tests and 5 subtests with real inference enabled. The self-test and JavaScript decision-support checks passed. The five comparison tests, two evaluator tests and thirteen benchmark-preparation tests passed in separate Python processes. Running all those FYP suites together exposed a pre-existing interaction between Ultralytics' global Pillow patch and the corrupt-image import test when optional `pi_heif` is absent. All 20 tests also passed in one process with `pi-heif==1.4.0` present in a temporary test directory.
- Before and after screenshots cover nine screens at 1440, 768 and 390 CSS pixels wide. Assessment photos are synthetic software inputs. The comparison-result screenshot uses the attributed Broken Interfaces display crop described below. Screenshot overlays are qualitative. No accuracy benchmark was run.

## Browser test coverage

The main Chromium smoke test covers catalogue and storage errors, invalid and repeated photos, replacement, loading, a failed scan, a review-required finding with confidence and boxes, real YOLO11n inference, report evidence states, quote calculation, print styling and QR capture in two tabs. The comparison smoke test covers real CPU inference from both models, invalid images, fixtures for box rendering, keyboard zoom, and CSV/JSON downloads. Desktop and mobile sizes use Chromium on Linux. Native Windows browsers and camera capture on a physical phone require a separate device check.

Before-and-after captures are local deliverables. Screenshots of phone assessment use generated software inputs. Comparison result captures use one CC BY 4.0 Broken Interfaces display crop and report qualitative detections. [Source and attribution](HOUDAN_V1_MODEL_REVIEW.md#private-qualitative-comparison)
