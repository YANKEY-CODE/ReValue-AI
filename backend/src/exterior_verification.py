from __future__ import annotations

from dataclasses import asdict
from typing import Any, get_args

from .gemini_client import GeminiAuthorizationRequired, GeminiClient, GeminiTemporaryUnavailable
from .schemas import DamageType, GeminiDamageVerification, ImageInput, Severity, YoloDetection


DAMAGE_VERIFICATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "damage_type": {"type": "string"},
                    "view": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["supports", "does_not_support", "uncertain"],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["minor", "moderate", "severe", "unknown"],
                    },
                    "visual_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["damage_type", "view", "status", "severity", "visual_evidence"],
            },
        }
    },
    "required": ["verifications"],
}


VERIFICATION_PROMPT = """Verify visible exterior damage from the provided photos
and YOLO candidate boxes. Return only observable evidence. Do not invent damage,
do not infer internal function, and do not produce A/B/C grades.
Use the exact image view label for each finding. The image views in order are:
"""


def verify_damage_with_gemini(
    *,
    images: list[ImageInput],
    yolo_detections: list[YoloDetection],
    client: GeminiClient | None = None,
) -> tuple[str, list[GeminiDamageVerification]]:
    client = client or GeminiClient()
    views = ", ".join(image.view for image in images)
    prompt = f"{VERIFICATION_PROMPT}{views}\nYOLO candidates:\n{[asdict(d) for d in yolo_detections]}"
    try:
        response = client.generate_structured(
            prompt=prompt,
            images=[asdict(image) for image in images],
            response_schema=DAMAGE_VERIFICATION_SCHEMA,
            use_search_grounding=False,
        )
    except GeminiAuthorizationRequired:
        return "not_configured", []
    except GeminiTemporaryUnavailable:
        return "temporarily_unavailable", []
    except (RuntimeError, ValueError):
        return "verification_failed", []

    if not isinstance(response, dict) or not isinstance(response.get("verifications"), list):
        return "verification_failed", []

    verifications = []
    valid_views = {image.view for image in images}
    for item in response["verifications"]:
        if not isinstance(item, dict):
            return "verification_failed", []
        damage = item.get("damage_type")
        view = item.get("view")
        state = item.get("status")
        severity = item.get("severity", "unknown")
        evidence = item.get("visual_evidence", [])
        if (damage not in get_args(DamageType) or not isinstance(view, str) or view not in valid_views
                or state not in ("supports", "does_not_support", "uncertain") or severity not in get_args(Severity)
                or not isinstance(evidence, list) or any(not isinstance(detail, str) for detail in evidence)):
            return "verification_failed", []
        verifications.append(GeminiDamageVerification(damage, view, state, severity, evidence))
    return "ok", verifications
