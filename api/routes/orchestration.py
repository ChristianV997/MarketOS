"""api.routes.orchestration — visibility into the workflow orchestration layer."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.routes.event_access import admit_event_read, event_read_gate
from backend.identity.errors import WorkspaceAccessDenied
from backend.identity.http import http_exception

router = APIRouter()
# The workflow event log cannot be bound to a workspace: its reads take no workspace argument and no producer writes a
# workspace into its records, so any read would show one workspace's events to another. Every log read therefore fails
# closed after the identity gate, and the store is never read. The rate-mesh health route carries no event data and
# stays open.


def _refuse_unscoped_event_log() -> None:
    raise http_exception(WorkspaceAccessDenied())


@router.get("/orchestration/health")
def platform_health():
    """Per-platform health state machines + rate mesh status."""
    from backend.orchestration.rate_mesh import rate_mesh
    return rate_mesh.status()


@router.get("/orchestration/workflows", dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
def recent_workflows(limit: int = 50):
    """Tail of the workflow event log. Fails closed: no read can be bound to a workspace."""
    _refuse_unscoped_event_log()


@router.get("/orchestration/workflows/incomplete", dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
def incomplete_workflows():
    """Workflows that started but never completed. Fails closed: no read can be bound to a workspace."""
    _refuse_unscoped_event_log()


@router.get("/orchestration/workflows/{workflow_id}", dependencies=[Depends(admit_event_read), Depends(event_read_gate)])
def workflow_detail(workflow_id: str):
    """Full event trace for one workflow. Fails closed: no read can be bound to a workspace."""
    _refuse_unscoped_event_log()


__all__ = ["router"]
