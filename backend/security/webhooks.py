"""Consolidated webhook signature verification, idempotency, and payload boundary."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any

from fastapi import HTTPException, Request

from backend.integrations.webhook_dedup import WebhookEventLedger

_log = logging.getLogger("marketos.security.webhooks")

# Global persistent ledger for all webhook deliveries
_webhook_ledger = WebhookEventLedger(max_entries=50_000, ttl_s=86_400.0)

# Maximum accepted payload size for webhooks (1 MB)
MAX_WEBHOOK_PAYLOAD_BYTES = 1_048_576
WEBHOOK_TIMESTAMP_TOLERANCE_S = 300.0


def get_webhook_ledger() -> WebhookEventLedger:
    return _webhook_ledger


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    tolerance_seconds: float = WEBHOOK_TIMESTAMP_TOLERANCE_S,
) -> bool:
    """Verify Stripe signature with constant-time comparison and timestamp tolerance."""
    if not signature_header or not secret:
        return False

    try:
        import stripe
        try:
            payload_str = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            stripe.WebhookSignature.verify_header(payload_str, signature_header, secret, tolerance=int(tolerance_seconds))
            return True
        except (ValueError, UnicodeDecodeError, stripe.error.SignatureVerificationError):
            return False
    except ImportError:
        pass

    # Pure python fallback implementation
    try:
        parts = dict(item.strip().split("=", 1) for item in signature_header.split(",") if "=" in item)
        timestamp_str = parts.get("t")
        expected_sig = parts.get("v1")
        if not timestamp_str or not expected_sig:
            return False

        timestamp = float(timestamp_str)
        now = time.time()
        if abs(now - timestamp) > tolerance_seconds:
            _log.warning("stripe_signature_timestamp_out_of_tolerance delta=%s", abs(now - timestamp))
            return False

        signed_payload = f"{timestamp_str}.".encode("utf-8") + payload
        computed = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, expected_sig)
    except Exception as exc:
        _log.warning("stripe_signature_verification_error error=%s", exc)
        return False


def verify_shopify_signature(
    payload: bytes,
    hmac_header: str,
    secret: str,
) -> bool:
    """Verify Shopify base64-encoded HMAC-SHA256 signature."""
    if not hmac_header or not secret:
        return False
    try:
        digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, hmac_header.strip())
    except Exception as exc:
        _log.warning("shopify_signature_verification_error error=%s", exc)
        return False


def verify_generic_hmac(
    payload: bytes,
    signature_header: str,
    secret: str,
    prefix: str = "sha256=",
) -> bool:
    """Verify generic hex HMAC-SHA256 signature with constant-time comparison."""
    if not signature_header or not secret:
        return False
    try:
        provided = signature_header.strip()
        if prefix and provided.startswith(prefix):
            provided = provided[len(prefix):]
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, provided)
    except Exception as exc:
        _log.warning("generic_hmac_verification_error error=%s", exc)
        return False


async def read_and_validate_webhook_body(
    request: Request,
    max_bytes: int = MAX_WEBHOOK_PAYLOAD_BYTES,
) -> bytes:
    """Read request body while strictly enforcing bounded payload size."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="payload_too_large: request body exceeds maximum allowed size",
                )
        except ValueError:
            pass

    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail="payload_too_large: request body exceeds maximum allowed size",
        )
    return body


def parse_safe_webhook_json(body: bytes) -> dict[str, Any]:
    """Parse JSON body while rejecting malformed or non-dict payloads."""
    try:
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise HTTPException(status_code=400, detail="invalid_payload: JSON object required")
        return parsed
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="invalid_payload: unparseable JSON")


__all__ = [
    "MAX_WEBHOOK_PAYLOAD_BYTES",
    "WEBHOOK_TIMESTAMP_TOLERANCE_S",
    "get_webhook_ledger",
    "parse_safe_webhook_json",
    "read_and_validate_webhook_body",
    "verify_generic_hmac",
    "verify_shopify_signature",
    "verify_stripe_signature",
]
