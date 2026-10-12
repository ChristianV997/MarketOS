"""Read-only Commerce Intelligence evaluation views.

Evaluation inputs are canonical event JSONL, so every route is operator-only (``api/routes/event_access.py``)
and evaluates only the events that belong to the verified principal's bound workspace.
"""
from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from fastapi import APIRouter, Depends

from api.routes.event_access import MAX_EVENT_JSONL_BYTES, admit_event_read, event_read_gate
from backend.identity.workspaces import WorkspaceAccess
from evaluation.commerce import EvaluationInput, compare_evaluations, evaluate_input, load_evaluation_input

router = APIRouter(prefix="/api/evaluations", tags=["commerce-evaluations"], dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = (ROOT / "artifacts").resolve()


def _safe_configured_path(name: str) -> Path | None:
    configured = os.getenv(name, "")
    if not configured:
        return None
    path = Path(configured).resolve()
    return path if ARTIFACTS in path.parents else None


def _bound_input(loaded: EvaluationInput, access: WorkspaceAccess) -> EvaluationInput:
    """Keep only the bound workspace's events. Events without a workspace are excluded; no artifact crosses workspaces."""
    events = tuple(event for event in loaded.events if event.workspace_id == access.workspace_id)
    return replace(loaded, events=events, artifact={})


def _oversized(path: Path | None) -> bool:
    """A configured file beyond the shared read bound is refused before it is parsed, as the canonical routes do."""
    return path is not None and path.is_file() and path.stat().st_size > MAX_EVENT_JSONL_BYTES


def _unconfigured(message: str) -> dict:
    return {
        "status": "blocked", "blockers": [message], "engines": {}, "overall": {},
        "read_only": True, "mutated": False, "network_calls": False,
    }


@router.get("")
def evaluation(access: WorkspaceAccess = Depends(event_read_gate)):
    path = _safe_configured_path("MARKETOS_EVENT_READ_JSONL_PATH")
    if path is None:
        return _unconfigured("MARKETOS_EVENT_READ_JSONL_PATH must point beneath artifacts/")
    if _oversized(path):
        return _unconfigured("MARKETOS_EVENT_READ_JSONL_PATH exceeds the bounded evaluation read size")
    report = evaluate_input(_bound_input(load_evaluation_input(path, source="jsonl"), access))
    return report.to_dict()


@router.get("/compare")
def evaluation_compare(access: WorkspaceAccess = Depends(event_read_gate)):
    baseline_path = _safe_configured_path("MARKETOS_EVALUATION_BASELINE_JSONL_PATH")
    current_path = _safe_configured_path("MARKETOS_EVALUATION_CURRENT_JSONL_PATH")
    if baseline_path is None or current_path is None:
        return _unconfigured("configured baseline and current evaluation JSONL paths are required beneath artifacts/")
    if _oversized(baseline_path) or _oversized(current_path):
        return _unconfigured("configured evaluation JSONL paths exceed the bounded evaluation read size")
    baseline = evaluate_input(_bound_input(load_evaluation_input(baseline_path, source="jsonl"), access))
    current = evaluate_input(_bound_input(load_evaluation_input(current_path, source="jsonl"), access))
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
