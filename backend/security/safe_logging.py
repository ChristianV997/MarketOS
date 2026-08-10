"""Redacted request logging helpers for the Phase 1 API."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any


_log = logging.getLogger("marketos.security")
_SECRET_KEY = re.compile(r"(key|token|secret|password|authorization|cookie|service[_-]?role|stripe|shopify|meta|tiktok|body|payload)", re.I)
_TOKEN_VALUE = re.compile(r"(?:bearer\s+)?[A-Za-z0-9_\-]{24,}", re.I)


def redact_secret_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return "<redacted>" if _TOKEN_VALUE.search(text) else text


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if _SECRET_KEY.search(str(key)):
            result[str(key)] = "<redacted>"
        elif isinstance(value, Mapping):
            result[str(key)] = redact_mapping(value)
        elif isinstance(value, (list, tuple)):
            result[str(key)] = [redact_mapping(item) if isinstance(item, Mapping) else redact_secret_value(item) for item in value]
        else:
            result[str(key)] = redact_secret_value(value)
    return result


def contains_forbidden_secret(value_or_mapping: Any) -> bool:
    if isinstance(value_or_mapping, Mapping):
        return any(_SECRET_KEY.search(str(key)) or contains_forbidden_secret(value) for key, value in value_or_mapping.items())
    if isinstance(value_or_mapping, (list, tuple)):
        return any(contains_forbidden_secret(value) for value in value_or_mapping)
    return bool(_TOKEN_VALUE.search(str(value_or_mapping))) if value_or_mapping is not None else False


def safe_log_event(name: str, **fields: Any) -> dict[str, Any]:
    safe = {"event": name, **redact_mapping(fields)}
    _log.info(json.dumps(safe, sort_keys=True, default=str))
    return safe


def log_request_start(*, request_id: str, method: str, path: str, route_family: str) -> dict[str, Any]:
    return safe_log_event("request_start", request_id=request_id, method=method, path=path, route_family=route_family)


def log_request_end(*, request_id: str, method: str, path: str, status_code: int, duration_ms: float, route_family: str, read_only: bool, public_network_gate_enabled: bool = False, event_target: str = "none") -> dict[str, Any]:
    return safe_log_event("request_end", request_id=request_id, method=method, path=path, status_code=status_code, duration_ms=round(duration_ms, 2), route_family=route_family, read_only=read_only, public_network_gate_enabled=public_network_gate_enabled, event_target=event_target)


__all__ = ["contains_forbidden_secret", "log_request_end", "log_request_start", "redact_mapping", "redact_secret_value", "safe_log_event"]
