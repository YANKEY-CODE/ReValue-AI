# ReValue UI redesign

## Audit and changes

The assessment page used several layers of dark, animated styling over a narrow mobile-first layout. Device setup left search failures looking like empty results. Photo requirements were hard to scan and errors could disappear before the user fixed them. The report put evidence status below prominent price styling, while the separate comparison page used its own visual system.

- Both sites now share offline typography, emerald accents, surfaces, buttons and keyboard focus styles. The assessment landing page explains the live and demo options and uses an illustrative studio image.
- The assessment separates device search, storage confirmation and the five photo views. It labels the required views, previews selected images, keeps their validation messages beside the affected slot, and distinguishes file selection from camera capture. QR capture uses the same styling.
- The analysis screen identifies the detector, shows candidate confidence and uncertainty, and preserves the existing review gate and provisional grade behaviour. The report distinguishes an evidence-based estimate, a lack of eligible evidence, a failed market request and illustrative demo values. It includes a print layout and the existing MYR quote calculator.
- The experimental comparison adds a removable file queue, drag-and-drop, batch progress, a box legend, and keyboard-accessible zoom. Exports and comparison parameters use the existing schema and settings. Accuracy still requires verified annotations.

## Windows launch

Use the existing project checkout and environment. Open PowerShell in the project directory and update the branch.

```powershell
Set-Location 'C:\Users\USER\ReValue-AI'
git switch fyp1-development
git pull --ff-only origin fyp1-development
```

Run the assessment in one PowerShell window and the comparison in a second window from the same directory. Leave each process running while using its site.

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\start-revalue.ps1
```

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\compare-models.ps1
```

The assessment opens at [127.0.0.1:8765](http://127.0.0.1:8765) and the comparison at [127.0.0.1:8766](http://127.0.0.1:8766).

## Verification

The main Chromium smoke test covers catalogue and storage errors, invalid and repeated photos, replacement, loading, a failed scan, a review-required finding with confidence and boxes, real YOLO11n inference, report evidence states, quote calculation, print styling and QR capture in two tabs. The comparison smoke test covers real CPU inference from both models, invalid images, fixtures for box rendering, keyboard zoom, and CSV/JSON downloads. Desktop and mobile sizes use Chromium on Linux. Native Windows browsers and camera capture on a physical phone require a separate device check.

Before-and-after captures are local deliverables. Screenshots of phone assessment use generated software inputs. Comparison result captures use one CC BY 4.0 Broken Interfaces display crop and report qualitative detections. [Source and attribution](HOUDAN_V1_MODEL_REVIEW.md#private-qualitative-comparison)
