"""Short-lived proof that a device's exterior scan produced a priceable grade."""

import hashlib
import hmac
import json
import secrets
import time

_KEY = secrets.token_bytes(32)
TTL_SECONDS = 15 * 60
PRICEABLE_BASES = {"provisional", "ai_corroborated"}


def _signature(device, grade, basis, issued_at):
    message = json.dumps([device["catalogue_id"], device["storage"], grade, basis, issued_at])
    return hmac.new(_KEY, message.encode(), hashlib.sha256).hexdigest()


def issue_receipt(device, grade, basis):
    if basis not in PRICEABLE_BASES or grade not in {"A", "B", "C", "C-"}:
        raise ValueError("Assessment is pending")
    issued_at = int(time.time())
    return f"{issued_at}.{basis}.{_signature(device, grade, basis, issued_at)}"


def verify_receipt(token, device, grade):
    if not isinstance(token, str) or len(token) > 120:
        return None
    try:
        timestamp, basis, signature = token.split(".")
        issued_at = int(timestamp)
    except ValueError:
        return None
    if basis not in PRICEABLE_BASES or not 0 <= time.time() - issued_at <= TTL_SECONDS:
        return None
    return basis if hmac.compare_digest(signature.encode(), _signature(device, grade, basis, issued_at).encode()) else None
