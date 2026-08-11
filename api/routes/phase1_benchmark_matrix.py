"""GET-only Phase 1 candidate benchmark workbench."""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from backend.security.rate_limit import check_rate_limit, event_read_policy
from evaluation.commerce.benchmark_matrix import build_benchmark_from_paths

router = APIRouter(prefix="/api/phase1", tags=["phase1-benchmark-matrix"])
ROOT = Path(__file__).resolve().parents[2]; ARTIFACTS = (ROOT / "artifacts").resolve()
def _safe_path(name: str) -> str | None:
    value = os.getenv(name, "")
    if not value: return None
    path = Path(value).resolve()
    return str(path) if ARTIFACTS in path.parents else None
@router.get("/benchmark-matrix")
def benchmark_matrix(request: Request = None):
    key = getattr(getattr(request, "client", None), "host", None) or "direct"; decision = check_rate_limit(event_read_policy(), key)
    if not decision.allowed: return JSONResponse({"status": "rate_limited", "read_only": True, "mutated": False}, status_code=429)
    return build_benchmark_from_paths(candidate_seed=_safe_path("MARKETOS_PHASE1_BENCHMARK_CANDIDATE_SEED"), readiness_report=_safe_path("MARKETOS_PHASE1_READINESS_REPORT"), evaluation_report=_safe_path("MARKETOS_PHASE1_EVALUATION_REPORT")).to_dict()
