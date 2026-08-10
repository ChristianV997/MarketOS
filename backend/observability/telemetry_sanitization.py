"""Privacy filters shared by Sentry and any future telemetry adapter."""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from backend.security.safe_logging import redact_mapping


_PII_KEY = re.compile(r"(email|phone|address|customer|full[_-]?name|first[_-]?name|last[_-]?name)", re.I)
_TOKEN_VALUE = re.compile(r"(?:bearer\s+)?[A-Za-z0-9_\-]{24,}", re.I)
_SAFE_TAG = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


def sanitize_telemetry_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in redact_mapping(mapping).items():
        if _PII_KEY.search(str(key)):
            result[str(key)] = "<redacted>"
        elif isinstance(value, Mapping):
            result[str(key)] = sanitize_telemetry_mapping(value)
        elif isinstance(value, list):
            result[str(key)] = [sanitize_telemetry_mapping(item) if isinstance(item, Mapping) else item for item in value]
        else:
            result[str(key)] = value
    return result


def sanitize_sentry_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a copy safe for Sentry; request data and identity are removed."""
    sanitized = sanitize_telemetry_mapping(event)
    sanitized.pop("user", None)
    request = sanitized.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("headers", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        sanitized["request"] = request
    sanitized["tags"] = sanitize_telemetry_mapping(sanitized.get("tags", {})) if isinstance(sanitized.get("tags"), Mapping) else {}
    return sanitized


def telemetry_contains_forbidden_data(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_PII_KEY.search(str(key)) or telemetry_contains_forbidden_data(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(telemetry_contains_forbidden_data(item) for item in value)
    return bool(_TOKEN_VALUE.search(str(value))) if value is not None else False


def safe_workspace_tag(value: Any) -> str:
    candidate = str(value or "")
    return candidate if _SAFE_TAG.fullmatch(candidate) else "workspace_redacted"


def safe_path_tag(path: Any) -> str:
    value = str(path or "").split("?", 1)[0]
    if value.startswith("/api/events"):
        return "/api/events/*"
    if value.startswith("/api/commerce-mvp/public-run"):
        return "/api/commerce-mvp/public-run"
    if value in {"/health", "/ready"}:
        return value
    return "/other"


__all__ = ["safe_path_tag", "safe_workspace_tag", "sanitize_sentry_event", "sanitize_telemetry_mapping", "telemetry_contains_forbidden_data"]
