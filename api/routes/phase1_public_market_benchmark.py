"""GET-only view of a server-configured public-market benchmark artifact."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from api.routes.event_access import admit_event_read, event_read_gate
from evaluation.commerce.public_market_benchmark import (
    build_public_market_benchmark,
    load_public_market_seed,
    redact_report_urls,
    synthesize_from_public_market,
    to_marketplace_trend_report,
)

# Derived from evaluation output: operator-only and throttled before identity (see api/routes/event_access.py).
router = APIRouter(prefix="/api/phase1", tags=["phase1-public-market-benchmark"], dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()
DEFAULT_SEED = ROOT / "tests" / "fixtures" / "public_market_benchmark" / "candidates.json"


def _safe_path(name: str) -> Path | None:
    value = os.getenv(name, "")
    if not value:
        return None
    path = Path(value).resolve()
    return path if ARTIFACTS in path.parents else None


def _with_canonical_projection(report: dict) -> dict:
    """Attach marketplace pillar + synthesis without mutating authority claims."""
    if not isinstance(report.get("candidate_results"), list):
        return {**report, "read_only": True, "mutated": False}
    try:
        marketplace = report.get("marketplace_trend_report")
        if not isinstance(marketplace, dict):
            marketplace = to_marketplace_trend_report(report).to_dict()
        synthesis = report.get("opportunity_synthesis")
        if not isinstance(synthesis, dict):
            synthesis = synthesize_from_public_market(report).to_dict()
    except (AttributeError, KeyError, TypeError, ValueError):
        # A malformed stored artifact must degrade to its own content, never to a 500.
        warnings = report.get("warnings") if isinstance(report.get("warnings"), list) else []
        return {**report, "warnings": sorted(set([*warnings, "canonical_projection_unavailable"])), "read_only": True, "mutated": False}
    return {
        **report,
        "marketplace_trend_report": marketplace,
        "opportunity_synthesis": synthesis,
        "read_only": True,
        "mutated": False,
    }


@router.get("/public-market-benchmark")
def public_market_benchmark(request: Request = None):
    configured = _safe_path("MARKETOS_PHASE1_PUBLIC_MARKET_BENCHMARK_REPORT")
    if configured and configured.is_file():
        from evaluation.commerce.readiness import load_sanitized_artifact
        value, warnings, _ = load_sanitized_artifact(configured)
        if value:
            enriched = _with_canonical_projection(redact_report_urls(value))
            enriched["warnings"] = sorted(set([*enriched.get("warnings", []), *warnings]))
            return enriched
    candidates, warnings = load_public_market_seed(DEFAULT_SEED)
    report = build_public_market_benchmark(candidates, allow_network=False).to_dict()
    report["warnings"] = sorted(set([*report["warnings"], *warnings, "server_artifact_not_configured_using_fixture_demo"]))
    return _with_canonical_projection(report)


__all__ = ["router"]
