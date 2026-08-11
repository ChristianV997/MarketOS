"""GET-only Phase 1 readiness cockpit endpoint."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.security.rate_limit import check_rate_limit, event_read_policy
from evaluation.commerce.readiness import build_from_paths

router = APIRouter(prefix="/api/phase1", tags=["phase1-readiness"])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()


def _safe_artifact_path(name: str) -> str | None:
    value = os.getenv(name, "")
    if not value:
        return None
    path = Path(value).resolve()
    return str(path) if ARTIFACTS in path.parents else None


@router.get("/readiness")
def readiness(request: Request = None):
    key = getattr(getattr(request, "client", None), "host", None) or "direct"
    decision = check_rate_limit(event_read_policy(), key)
    if not decision.allowed:
        return JSONResponse({"status": "rate_limited", "retry_after_seconds": decision.retry_after_seconds, "read_only": True, "mutated": False}, status_code=429, headers={"Retry-After": str(decision.retry_after_seconds)})
    # Artifact locations are operator-configured server-side. Browser callers
    # cannot choose a path and no report is generated as a side effect.
    return build_from_paths(
        validation_artifact=_safe_artifact_path("MARKETOS_PHASE1_VALIDATION_ARTIFACT"),
        evaluation_report=_safe_artifact_path("MARKETOS_PHASE1_EVALUATION_REPORT"),
        comparison_report=_safe_artifact_path("MARKETOS_PHASE1_COMPARISON_REPORT"),
        validation_pack_report=_safe_artifact_path("MARKETOS_PHASE1_VALIDATION_PACK_REPORT"),
        benchmark_report=_safe_artifact_path("MARKETOS_PHASE1_BENCHMARK_REPORT"),
        public_market_benchmark_report=_safe_artifact_path("MARKETOS_PHASE1_PUBLIC_MARKET_BENCHMARK_REPORT"),
    ).to_dict()


__all__ = ["router"]
