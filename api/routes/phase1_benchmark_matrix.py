"""GET-only Phase 1 candidate benchmark workbench."""
from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, Depends, Request
from api.routes.event_access import admit_event_read, event_read_gate
from evaluation.commerce.benchmark_matrix import build_benchmark_from_paths

# Derived from evaluation output: operator-only and throttled before identity (see api/routes/event_access.py).
router = APIRouter(prefix="/api/phase1", tags=["phase1-benchmark-matrix"], dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
ROOT = Path(__file__).resolve().parents[2]; ARTIFACTS = (ROOT / "artifacts").resolve()
def _safe_path(name: str) -> str | None:
    value = os.getenv(name, "")
    if not value: return None
    path = Path(value).resolve()
    return str(path) if ARTIFACTS in path.parents else None
@router.get("/benchmark-matrix")
def benchmark_matrix(request: Request = None):
    report = build_benchmark_from_paths(candidate_seed=_safe_path("MARKETOS_PHASE1_BENCHMARK_CANDIDATE_SEED"), readiness_report=_safe_path("MARKETOS_PHASE1_READINESS_REPORT"), evaluation_report=_safe_path("MARKETOS_PHASE1_EVALUATION_REPORT")).to_dict()
    # Absolute server paths stay on the server: the response names each artifact, not where it lives.
    report["source_artifacts"] = {name: Path(value).name for name, value in report.get("source_artifacts", {}).items()}
    return report
