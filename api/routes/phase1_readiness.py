"""GET-only Phase 1 readiness cockpit endpoint."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from api.routes.event_access import admit_event_read, event_read_gate
from evaluation.commerce.readiness import build_from_paths

# Derived from evaluation output: operator-only and throttled before identity (see api/routes/event_access.py).
router = APIRouter(prefix="/api/phase1", tags=["phase1-readiness"], dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
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
    # Artifact locations are operator-configured server-side. Browser callers
    # cannot choose a path and no report is generated as a side effect.
    report = build_from_paths(
        validation_artifact=_safe_artifact_path("MARKETOS_PHASE1_VALIDATION_ARTIFACT"),
        evaluation_report=_safe_artifact_path("MARKETOS_PHASE1_EVALUATION_REPORT"),
        comparison_report=_safe_artifact_path("MARKETOS_PHASE1_COMPARISON_REPORT"),
        validation_pack_report=_safe_artifact_path("MARKETOS_PHASE1_VALIDATION_PACK_REPORT"),
        benchmark_report=_safe_artifact_path("MARKETOS_PHASE1_BENCHMARK_REPORT"),
        public_market_benchmark_report=_safe_artifact_path("MARKETOS_PHASE1_PUBLIC_MARKET_BENCHMARK_REPORT"),
    ).to_dict()
    # Absolute server paths stay on the server: the response names each artifact, not where it lives.
    report["source_artifacts"] = {name: Path(value).name for name, value in report.get("source_artifacts", {}).items()}
    return report


__all__ = ["router"]
