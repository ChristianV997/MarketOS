"""Read-only service-delivery projection endpoint."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.security.rate_limit import check_rate_limit, event_read_policy
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage

router = APIRouter(prefix="/api/service-delivery", tags=["service-delivery"])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()
ENDPOINT = "/api/service-delivery/workbench"
SUPPORTED_VERSIONS = {"service-engagement-projection-v1", "service-delivery-plane-v1"}
# Operator dump bound: larger than TrustOS client-evidence export (64KiB),
# aligned with the documented workbench display window (500 rows).
MAX_PROJECTION_BYTES = 1_048_576
MAX_ENGAGEMENTS = 500


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "service-engagement-projection-v1",
        "availability": "unavailable",
        "live_endpoint": ENDPOINT,
        "live_endpoint_status": "unavailable",
        "read_only": True,
        "generated_at": "deterministic",
        "engagements": [],
        "diagnostics": [reason],
        "input_contract": "unknown",
        "network_calls": False,
        "mutated": False,
    }


def _safe_projection_path() -> Path | None:
    value = os.getenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", "")
    if not value:
        return None
    path = Path(value).resolve()
    return path if ARTIFACTS in path.parents and path.is_file() else None


def _money_currency(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    currency = value.get("currency")
    if currency is None or currency == "":
        return None
    return str(currency)


def _economics_currencies(row: Mapping[str, Any]) -> list[str]:
    """Currencies on display economics only. Do not mix in engagement.fee
    (package-default quote) — the producer copies service_fee into
    economics.fee for the actual billed currency.
    """
    economics = row.get("economics")
    if not isinstance(economics, Mapping):
        return []
    found: list[str] = []
    for key in ("fee", "contribution"):
        currency = _money_currency(economics.get(key))
        if currency:
            found.append(currency)
    return found


def _validate_rows(rows: list[Any]) -> str | None:
    if len(rows) > MAX_ENGAGEMENTS:
        return "service_delivery_projection_oversized"
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return "service_delivery_projection_row_must_be_object"
        engagement_id = row.get("engagement_id")
        if engagement_id is None or str(engagement_id).strip() == "":
            return "service_delivery_projection_row_missing_engagement_id"
        key = str(engagement_id)
        if key in seen:
            return "service_delivery_projection_duplicate_engagement_id"
        seen.add(key)
        currencies = _economics_currencies(row)
        if currencies and len(set(currencies)) > 1:
            return "service_delivery_projection_currency_mismatch"
    return None


def _load_projection(path: Path | None) -> dict[str, Any]:
    if path is None:
        return _unavailable("service_delivery_projection_not_configured")
    try:
        if path.stat().st_size > MAX_PROJECTION_BYTES:
            return _unavailable("service_delivery_projection_oversized")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _unavailable("service_delivery_projection_unavailable")
    if not isinstance(value, Mapping):
        return _unavailable("service_delivery_projection_root_must_be_object")
    payload = dict(value)
    version = str(payload.get("schema_version", payload.get("report_version", "")))
    if version not in SUPPORTED_VERSIONS:
        return _unavailable("unsupported_service_delivery_projection")
    if payload.get("read_only") is not True or payload.get("network_calls") is True or payload.get("mutated") is True:
        return _unavailable("unsafe_service_delivery_projection")
    if check_workspace_leakage(payload, client_safe=True):
        return _unavailable("service_delivery_projection_failed_workspace_isolation")
    rows = payload.get("engagements", payload.get("packages", []))
    if not isinstance(rows, list):
        return _unavailable("service_delivery_projection_rows_must_be_array")
    row_reason = _validate_rows(rows)
    if row_reason:
        return _unavailable(row_reason)
    payload.update({
        "live_endpoint": ENDPOINT,
        "live_endpoint_status": "available_read_only",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
    })
    diagnostics = payload.get("diagnostics", [])
    payload["diagnostics"] = [*(diagnostics if isinstance(diagnostics, list) else []), "read_only_artifact_projection"]
    return payload


@router.get("/workbench")
def workbench(request: Request = None):
    key = getattr(getattr(request, "client", None), "host", None) or "direct"
    decision = check_rate_limit(event_read_policy(), key)
    if not decision.allowed:
        return JSONResponse({"status": "rate_limited", "read_only": True, "mutated": False}, status_code=429)
    return _load_projection(_safe_projection_path())


__all__ = ["router", "workbench", "MAX_ENGAGEMENTS", "MAX_PROJECTION_BYTES"]
