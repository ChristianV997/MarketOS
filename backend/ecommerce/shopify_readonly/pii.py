"""Deterministic redaction helpers for local, read-only import artifacts."""
from __future__ import annotations

import hashlib
import re
from typing import Any


_SALT = "marketos-shopify-readonly"


def normalize_secret_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def hash_pii(value: Any, salt: str = _SALT) -> str | None:
    normalized = normalize_secret_text(value)
    if not normalized:
        return None
    return hashlib.sha256(f"{salt}:{normalized}".encode("utf-8")).hexdigest()


def redact_name(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized:
        return "[redacted]"
    parts = normalized.split(" ")
    return " ".join(f"{part[0].upper()}***" for part in parts if part)


def redact_email(value: Any) -> str | None:
    digest = hash_pii(value)
    return f"email:{digest[:12]}" if digest else None


def redact_phone(value: Any) -> str | None:
    digest = hash_pii(re.sub(r"\D", "", str(value or "")))
    return f"phone:{digest[:12]}" if digest else None


def redact_address(value: Any) -> str:
    return "[redacted-address]" if value else ""


def redact_customer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow-safe customer payload with raw direct identifiers removed."""
    value = dict(payload or {})
    email = value.pop("email", None); phone = value.pop("phone", None)
    first = value.pop("first_name", None); last = value.pop("last_name", None)
    for key in ("address", "addresses", "default_address", "note", "last_name", "name"):
        value.pop(key, None)
    value["email_hash"] = hash_pii(email)
    value["phone_hash"] = hash_pii(phone)
    value["name_redacted"] = redact_name(" ".join(item for item in (str(first or ""), str(last or "")) if item))
    return value


__all__ = ["hash_pii", "normalize_secret_text", "redact_address", "redact_customer_payload", "redact_email", "redact_name", "redact_phone"]
