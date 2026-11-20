"""Validation shared by guided uploads and exterior inference."""

from __future__ import annotations

import base64
from binascii import Error as Base64Error
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.Image import open as open_image

from .schemas import ImageInput

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
IMAGE_MIME_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
EXTERIOR_VIEWS = {"front", "back", "camera", "left_side", "right_side", "side", "unknown"}


def decode_image(image: ImageInput):
    """Return an upright RGB Pillow image with validated bytes and dimensions."""
    if not isinstance(image.bytes_b64, str) or not image.bytes_b64:
        raise ValueError(f"Image bytes are required for {image.view}.")
    if len(image.bytes_b64) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError(f"Image for {image.view} exceeds 8 MiB.")
    try:
        raw = base64.b64decode(image.bytes_b64, validate=True)
    except (Base64Error, ValueError) as exc:
        raise ValueError(f"Invalid base64 image for {image.view}.") from exc
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image for {image.view} exceeds 8 MiB.")

    # Keep Pillow's reader because Ultralytics replaces Image.open with a HEIF fallback.
    try:
        with open_image(BytesIO(raw), formats=list(IMAGE_MIME_TYPES)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                raise ValueError(f"Image for {image.view} exceeds 16 megapixels.")
            if image.mime_type and image.mime_type != IMAGE_MIME_TYPES[source.format]:
                raise ValueError(f"Image format and MIME type disagree for {image.view}.")
            if getattr(source, "is_animated", False):
                raise ValueError(f"Use a still image for {image.view}.")
            return ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError(f"Upload a readable JPEG, PNG or WebP for {image.view}.") from exc
