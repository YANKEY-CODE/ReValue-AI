from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any

from .image_upload import decode_image
from .schemas import DamageType, ImageInput, ViewType, YoloDetection


YOLO_MODEL_NAME = "revalue_exterior_yolo11n_v0.2"
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "revalue_exterior_yolo11n_v0.2.pt"
DEFAULT_IMGSZ = 640
DEFAULT_CONF = 0.25
_INFERENCE_LOCK = Lock()
RAW_CLASS_NAMES = {
    0: "generic_crack",
    1: "scratch",
}


class YoloDetectorUnavailable(RuntimeError):
    """Raised when YOLO dependencies or model weights are unavailable."""


def map_yolo_class_to_damage_type(raw_class: str, view: ViewType) -> DamageType | None:
    """Map raw YOLO class names to ReValue atomic damage only when safe."""

    raw = raw_class.strip().lower()
    if raw == "scratch":
        return "scratch"
    if raw == "generic_crack" and view == "front":
        return "screen_crack"
    if raw == "generic_crack" and view == "back":
        return "back_glass_crack"
    return None


@lru_cache(maxsize=1)
def load_yolo_model(model_path: str = str(DEFAULT_MODEL_PATH)) -> Any:
    path = Path(model_path)
    if not path.is_file():
        raise YoloDetectorUnavailable("The configured exterior model weights were not found.")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise YoloDetectorUnavailable("Install the exterior model dependencies.") from exc
    try:
        model = YOLO(str(path))
        if model.task != "detect":
            raise ValueError("Expected detection weights")
        return model
    except Exception as exc:
        raise YoloDetectorUnavailable("The configured exterior detection model could not be loaded.") from exc


def _to_list(value: Any) -> list[Any]:
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value)


def _detections_from_result(result: Any, view: ViewType, source: str) -> list[YoloDetection]:
    boxes = getattr(result, "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []

    names = getattr(result, "names", None) or RAW_CLASS_NAMES
    class_ids = _to_list(boxes.cls)
    confidences = _to_list(boxes.conf)
    xyxy_values = _to_list(boxes.xyxy)

    detections: list[YoloDetection] = []
    for class_id_raw, confidence_raw, xyxy_raw in zip(class_ids, confidences, xyxy_values):
        class_id = int(class_id_raw)
        raw_class = str(names.get(class_id, RAW_CLASS_NAMES.get(class_id, f"class_{class_id}")))
        mapped = map_yolo_class_to_damage_type(raw_class, view)
        detections.append(
            YoloDetection(
                raw_class=raw_class,
                damage_type=mapped,
                confidence=float(confidence_raw),
                view=view,
                bounding_box_xyxy=[float(v) for v in xyxy_raw],
                source=source,
                requires_gemini_resolution=mapped is None,
            )
        )
    return detections


def detect_exterior_damage(
    images: list[ImageInput],
    *,
    model_path: str = str(DEFAULT_MODEL_PATH),
    imgsz: int = DEFAULT_IMGSZ,
    conf: float = DEFAULT_CONF,
) -> list[YoloDetection]:
    import numpy as np

    if not images:
        raise ValueError("At least one exterior image is required.")
    # Ultralytics accepts in-memory BGR arrays. Keep images off disk and preserve view order.
    with _INFERENCE_LOCK:
        frames = [np.asarray(decode_image(image))[:, :, ::-1].copy() for image in images]
        try:
            model = load_yolo_model(model_path)
            results = model.predict(source=frames, imgsz=imgsz, conf=conf, verbose=False, save=False)
            model_name = Path(model_path).stem
            return [
                detection
                for image, result in zip(images, results, strict=True)
                for detection in _detections_from_result(result, image.view, model_name)
            ]
        except YoloDetectorUnavailable:
            raise
        except Exception as exc:
            raise YoloDetectorUnavailable("Exterior model inference did not complete.") from exc
