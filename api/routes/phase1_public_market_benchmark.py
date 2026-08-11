"""GET-only view of a server-configured public-market benchmark artifact."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.security.rate_limit import check_rate_limit, event_read_policy
from evaluation.commerce.public_market_benchmark import build_public_market_benchmark, load_public_market_seed

router = APIRouter(prefix="/api/phase1", tags=["phase1-public-market-benchmark"])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()
DEFAULT_SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"


def _safe_path(name: str) -> Path | None:
    value = os.getenv(name, "")
    if not value:
        return None
    path = Path(value).resolve()
    return path if ARTIFACTS in path.parents else None


@router.get("/public-market-benchmark")
def public_market_benchmark(request: Request = None):
    key = getattr(getattr(request, "client", None), "host", None) or "direct"
    decision = check_rate_limit(event_read_policy(), key)
    if not decision.allowed:
        return JSONResponse({"status": "rate_limited", "read_only": True, "mutated": False}, status_code=429)
    configured = _safe_path("MARKETOS_PHASE1_PUBLIC_MARKET_BENCHMARK_REPORT")
    if configured and configured.is_file():
        from evaluation.commerce.readiness import load_sanitized_artifact
        value, warnings, _ = load_sanitized_artifact(configured)
        if value:
            return {**value, "warnings": sorted(set([*value.get("warnings", []), *warnings])), "read_only": True, "mutated": False}
    candidates, warnings = load_public_market_seed(DEFAULT_SEED)
    report = build_public_market_benchmark(candidates, allow_network=False).to_dict()
    report["warnings"] = sorted(set([*report["warnings"], *warnings, "server_artifact_not_configured_using_fixture_demo"]))
    return report


__all__ = ["router"]
