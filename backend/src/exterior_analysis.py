from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .exterior_verification import verify_damage_with_gemini
from .grading_rules import grade_from_atomic_damage
from .hybrid_merge import merge_damage_signals
from .image_upload import EXTERIOR_VIEWS
from .schemas import GradeResult, ImageInput, YoloDetection
from .yolo_detector import DEFAULT_IMGSZ, DEFAULT_MODEL_PATH, YoloDetectorUnavailable, detect_exterior_damage


def analyze_exterior(
    images: list[ImageInput],
    *,
    run_gemini_verification: bool = True,
    detector: Callable[[list[ImageInput]], list[YoloDetection]] | None = None,
) -> dict[str, Any]:
    """Run detection, optional AI corroboration, then deterministic grading."""
    model_path = os.environ.get("REVALUE_DETECTOR_WEIGHTS") or str(DEFAULT_MODEL_PATH)
    model_name = Path(model_path).stem if detector is None else None
    result = {
        "yolo_model": model_name,
        "assessment_basis": "unavailable",
        "detections": [],
        "gemini_verifications": [],
        "merged_damage": [],
    }
    try:
        views = [image.view for image in images]
        if not {"front", "back"}.issubset(views):
            raise ValueError("Front and back photos are required for an exterior grade.")
        if len(views) > 5 or len(views) != len(set(views)) or any(view not in EXTERIOR_VIEWS for view in views):
            raise ValueError("Supply up to five distinct exterior views.")
        supplied_photos = [image.bytes_b64 for image in images if image.bytes_b64]
        if len(supplied_photos) != len(set(supplied_photos)):
            raise ValueError("Use a separate photo for each exterior view.")
        if detector is None:
            try:
                imgsz = int(os.environ.get("REVALUE_DETECTOR_IMGSZ", DEFAULT_IMGSZ))
                if imgsz < 32 or imgsz % 32:
                    raise ValueError("Expected a positive multiple of 32")
            except ValueError as exc:
                raise YoloDetectorUnavailable("The exterior model image size must be a positive multiple of 32.") from exc
            detections = detect_exterior_damage(images, model_path=model_path, imgsz=imgsz)
        else:
            detections = detector(images)
    except (ValueError, YoloDetectorUnavailable, ImportError) as exc:
        invalid = isinstance(exc, ValueError)
        reason = "invalid_image_payload" if invalid else "yolo_detector_unavailable"
        message = str(exc) if not isinstance(exc, ImportError) else "Install the exterior model dependencies."
        return {
            **result,
            "status": "error" if invalid else "blocked",
            "error": message,
            "grade": asdict(GradeResult("pending", [reason], "Exterior analysis did not complete.")),
        }

    gemini_status, verifications = "skipped", []
    if run_gemini_verification:
        gemini_status, verifications = verify_damage_with_gemini(images=images, yolo_detections=detections)

    merged = merge_damage_signals(detections, verifications)
    grade = grade_from_atomic_damage(merged)
    contested = any(item.manual_review for item in merged)
    unresolved = any(item.damage_type is None for item in detections)
    grade_items = [item for item in merged if item.grade_affecting]
    corroborated = bool(grade_items) and all(item.support == "hybrid_supported" for item in grade_items)
    basis = "ai_corroborated" if corroborated else "provisional"
    if not merged and not unresolved:
        grade = GradeResult("A", ["no_damage_detected"], "No damage was detected in these photos. Check the phone in person before treating it as clean.")
    if contested or unresolved:
        basis = "review_required"
        grade = GradeResult("pending", ["unresolved_damage"], "A damage candidate needs review before valuation.")

    return {
        "status": "ok",
        "yolo_model": model_name,
        "assessment_basis": basis,
        "gemini_status": gemini_status,
        "detections": [asdict(item) for item in detections],
        "gemini_verifications": [asdict(item) for item in verifications],
        "merged_damage": [asdict(item) for item in merged],
        "grade": asdict(grade),
        "notes": [grade.note],
    }
