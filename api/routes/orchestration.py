"""api.routes.orchestration — visibility into the workflow orchestration layer."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/orchestration/health")
def platform_health():
    """Per-platform health state machines + rate mesh status."""
    from backend.orchestration.rate_mesh import rate_mesh
    return rate_mesh.status()


@router.get("/orchestration/workflows")
def recent_workflows(limit: int = 50):
    """Tail of the workflow event log."""
    from backend.orchestration.event_store import event_store
    return {"events": event_store.tail(limit)}


@router.get("/orchestration/workflows/incomplete")
def incomplete_workflows():
    """Workflows that started but never completed (crash candidates)."""
    from backend.orchestration.event_store import event_store
    return {"incomplete": event_store.incomplete_workflows()}


@router.get("/orchestration/workflows/{workflow_id}")
def workflow_detail(workflow_id: str):
    """Full event trace for one workflow."""
    from backend.orchestration.event_store import event_store
    return {"workflow_id": workflow_id,
            "events": event_store.events_for(workflow_id)}


__all__ = ["router"]
