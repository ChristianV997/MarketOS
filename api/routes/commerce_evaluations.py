"""Read-only Commerce Intelligence evaluation views."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.security.rate_limit import check_rate_limit, event_read_policy
from evaluation.commerce import compare_evaluations, evaluate_input, load_evaluation_input

router = APIRouter(prefix="/api/evaluations", tags=["commerce-evaluations"])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()


def _safe_configured_path(name: str) -> Path | None:
    configured = os.getenv(name, "")
    if not configured:
        return None
    path = Path(configured).resolve()
    return path if ARTIFACTS in path.parents else None


def _limited(request: Request | None) -> JSONResponse | None:
    key = getattr(getattr(request, "client", None), "host", None) or "direct"
    decision = check_rate_limit(event_read_policy(), key)
    if decision.allowed:
        return None
    return JSONResponse(
        {"status": "rate_limited", "retry_after_seconds": decision.retry_after_seconds, "read_only": True, "mutated": False},
        status_code=429,
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def _unconfigured(message: str) -> dict:
    return {
        "status": "blocked", "blockers": [message], "engines": {}, "overall": {},
        "read_only": True, "mutated": False, "network_calls": False,
    }


@router.get("")
def evaluation(request: Request = None):
    if limited := _limited(request):
        return limited
    path = _safe_configured_path("MARKETOS_EVENT_READ_JSONL_PATH")
    if path is None:
        return _unconfigured("MARKETOS_EVENT_READ_JSONL_PATH must point beneath artifacts/")
    report = evaluate_input(load_evaluation_input(path, source="jsonl"))
    return report.to_dict()


@router.get("/compare")
def evaluation_compare(request: Request = None):
    if limited := _limited(request):
        return limited
    baseline_path = _safe_configured_path("MARKETOS_EVALUATION_BASELINE_JSONL_PATH")
    current_path = _safe_configured_path("MARKETOS_EVALUATION_CURRENT_JSONL_PATH")
    if baseline_path is None or current_path is None:
        return _unconfigured("configured baseline and current evaluation JSONL paths are required beneath artifacts/")
    baseline = evaluate_input(load_evaluation_input(baseline_path, source="jsonl"))
    current = evaluate_input(load_evaluation_input(current_path, source="jsonl"))
    comparison = compare_evaluations(baseline, current)
    return {
        "baseline": baseline.to_dict(), "current": current.to_dict(),
        "comparison": comparison.to_dict(), "read_only": True, "mutated": False,
    }


@router.get("/readiness")
def evaluation_readiness():
    current = _safe_configured_path("MARKETOS_EVENT_READ_JSONL_PATH")
    baseline = _safe_configured_path("MARKETOS_EVALUATION_BASELINE_JSONL_PATH")
    comparison = _safe_configured_path("MARKETOS_EVALUATION_CURRENT_JSONL_PATH")
    return {
        "framework": "commerce-evaluation-v1", "configured": current is not None,
        "current_jsonl_configured": current is not None,
        "comparison_configured": baseline is not None and comparison is not None,
        "read_only": True, "mutated": False, "network_calls": False,
        "write_methods": [],
    }


__all__ = ["router"]
