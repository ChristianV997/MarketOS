from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query

from backend.operations.operations_registry import get_operations_registry
from backend.operations.operations_runner import create_operating_plan_cycle, create_progress_review, update_task_status
from backend.operations.operating_plan_builder import build_operating_plan_from_optimization

router = APIRouter(prefix="/api/operations", tags=["operations"])


def _limit(value: int, maximum: int) -> int:
    return max(1, min(int(value), maximum))


@router.post("/plans")
def create_plan(payload: dict[str, Any] = Body(default={} )):
    try:
        max_tasks = _limit(payload.get("max_tasks", 20), 100)
        return create_operating_plan_cycle(
            workspace_id=str(payload.get("workspace_id", "default")),
            optimization_id=payload.get("optimization_id"),
            horizon=str(payload.get("horizon", "weekly")),
            max_tasks=max_tasks,
            daily_hour_capacity=float(payload.get("daily_hour_capacity", 4.0)),
            create_calendar=bool(payload.get("create_calendar", True)),
            create_packets=bool(payload.get("create_packets", True)),
            create_review_cadence=bool(payload.get("create_review_cadence", True)),
        )
    except Exception as exc:
        return {"status": "failed", "errors": [str(exc)]}


@router.get("/plans")
def list_plans(workspace_id: str | None = None, horizon: str | None = None, status: str | None = None, limit: int = Query(50, le=100)):
    return {"status": "completed", "plans": [x.to_dict() for x in get_operations_registry().list_plans(workspace_id, horizon, status, _limit(limit, 100))]}


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    item = get_operations_registry().get_plan(plan_id)
    return item.to_dict() if item else {"status": "not_found", "plan_id": plan_id}


@router.get("/tasks")
def list_tasks(workspace_id: str | None = None, plan_id: str | None = None, status: str | None = None, task_type: str | None = None, limit: int = Query(200, le=500)):
    return {"status": "completed", "tasks": [x.to_dict() for x in get_operations_registry().list_tasks(workspace_id, plan_id, status, task_type, _limit(limit, 500))]}


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    item = get_operations_registry().get_task(task_id)
    return item.to_dict() if item else {"status": "not_found", "task_id": task_id}


@router.post("/tasks/{task_id}/status")
def set_task_status(task_id: str, payload: dict[str, Any] = Body(default={} )):
    return update_task_status(task_id, str(payload.get("status", "")), str(payload.get("note", "")), payload.get("produced_outputs"))


@router.get("/task-packets")
def list_packets(workspace_id: str | None = None, plan_id: str | None = None, limit: int = Query(200, le=500)):
    return {"status": "completed", "packets": [x.to_dict() for x in get_operations_registry().list_task_packets(workspace_id, plan_id, _limit(limit, 500))]}


@router.get("/task-packets/{packet_id}")
def get_packet(packet_id: str):
    item = get_operations_registry().get_task_packet(packet_id)
    return item.to_dict() if item else {"status": "not_found", "packet_id": packet_id}


@router.get("/calendars")
def list_calendars(workspace_id: str | None = None, plan_id: str | None = None, limit: int = Query(50, le=100)):
    return {"status": "completed", "calendars": [x.to_dict() for x in get_operations_registry().list_calendars(workspace_id, plan_id, _limit(limit, 100))]}


@router.get("/calendars/{calendar_id}")
def get_calendar(calendar_id: str):
    item = get_operations_registry().get_calendar(calendar_id)
    return item.to_dict() if item else {"status": "not_found", "calendar_id": calendar_id}


@router.get("/calendars/{calendar_id}/ics")
def get_calendar_ics(calendar_id: str):
    item = get_operations_registry().get_calendar(calendar_id)
    if item is None:
        return {"status": "not_found", "calendar_id": calendar_id}
    return {"status": "completed", "content_type": "text/calendar", "local_only": True, "content": item.to_ics_text()}


@router.get("/review-cadences")
def list_cadences(workspace_id: str | None = None, plan_id: str | None = None, limit: int = Query(50, le=100)):
    return {"status": "completed", "review_cadences": [x.to_dict() for x in get_operations_registry().list_review_cadences(workspace_id, plan_id, _limit(limit, 100))]}


@router.get("/review-cadences/{cadence_id}")
def get_cadence(cadence_id: str):
    item = get_operations_registry().get_review_cadence(cadence_id)
    return item.to_dict() if item else {"status": "not_found", "cadence_id": cadence_id}


@router.post("/progress-review")
def progress_review(payload: dict[str, Any] = Body(default={} )):
    return create_progress_review(str(payload.get("plan_id", "")), payload.get("completed_task_ids"), payload.get("blocked_task_ids"), payload.get("cancelled_task_ids"), payload.get("produced_outputs"))


@router.get("/progress-snapshots")
def list_progress(workspace_id: str | None = None, plan_id: str | None = None, limit: int = Query(100, le=200)):
    return {"status": "completed", "progress_snapshots": [x.to_dict() for x in get_operations_registry().list_progress_snapshots(workspace_id, plan_id, _limit(limit, 200))]}


@router.get("/progress-snapshots/{snapshot_id}")
def get_progress(snapshot_id: str):
    item = get_operations_registry().get_progress_snapshot(snapshot_id)
    return item.to_dict() if item else {"status": "not_found", "snapshot_id": snapshot_id}
