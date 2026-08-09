from __future__ import annotations

import time
from typing import Any

from .calendar_artifacts import build_operating_calendar
from .operating_plan_builder import build_operating_plan_from_optimization, build_task_packets_for_plan
from .operations_registry import get_operations_registry
from .review_cadence import build_progress_snapshot, build_review_cadence
from .task_models import OperatingPlan, OperatingTask, TaskPacket, TASK_STATUSES


def _sync(name: str, obj: Any) -> dict[str, Any]:
    try:
        from backend.obsidian import sync as obsidian_sync
        return getattr(obsidian_sync, name)(obj)
    except Exception as exc:
        return {"status": "warning", "warnings": [f"obsidian_sync_failed: {exc}"]}


def create_operating_plan_cycle(
    workspace_id: str = "default",
    optimization_id: str | None = None,
    horizon: str = "weekly",
    max_tasks: int = 20,
    daily_hour_capacity: float = 4.0,
    create_calendar: bool = True,
    create_packets: bool = True,
    create_review_cadence: bool = True,
) -> dict[str, Any]:
    registry = get_operations_registry()
    plan = build_operating_plan_from_optimization(workspace_id, optimization_id, horizon, max_tasks, daily_hour_capacity)
    for task in plan.tasks:
        task.metadata["plan_id"] = plan.plan_id
        registry.register_task(task)
    registry.register_plan(plan)
    packets = build_task_packets_for_plan(plan) if create_packets else []
    for packet in packets:
        registry.register_task_packet(packet)
    calendar = build_operating_calendar(plan) if create_calendar else None
    if calendar:
        registry.register_calendar(calendar)
    cadence = build_review_cadence(plan) if create_review_cadence else None
    if cadence:
        registry.register_review_cadence(cadence)
        plan.review_cadence_id = cadence.cadence_id
        plan.updated_at = time.time()
        registry.update_plan(plan)
    obsidian = {}
    if plan:
        obsidian["plan"] = _sync("sync_operating_plan_note", plan)
    if packets:
        obsidian["packets"] = [_sync("sync_task_packet_note", packet) for packet in packets]
    if calendar:
        obsidian["calendar"] = _sync("sync_operating_calendar_note", calendar)
    if cadence:
        obsidian["cadence"] = _sync("sync_review_cadence_note", cadence)
    return {
        "plan": plan.to_dict(),
        "tasks": [task.to_dict() for task in plan.tasks],
        "packets": [packet.to_dict() for packet in packets],
        "calendar": calendar.to_dict() if calendar else None,
        "review_cadence": cadence.to_dict() if cadence else None,
        "obsidian": obsidian,
        "status": "partial" if plan.status == "blocked" else "completed",
        "warnings": ["Tasks and endpoint payloads are planning references only; no task was executed."],
    }


def update_task_status(task_id: str, status: str, note: str = "", produced_outputs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    registry = get_operations_registry()
    task = registry.get_task(task_id)
    if task is None:
        return {"status": "not_found", "task_id": task_id}
    if status not in TASK_STATUSES:
        return {"status": "blocked", "task_id": task_id, "blocked_reasons": ["invalid_task_status"]}
    task.status = status
    task.updated_at = time.time()
    if note:
        task.metadata["operator_note"] = note
    if produced_outputs:
        task.metadata["produced_outputs"] = list(produced_outputs)
    registry.update_task(task)
    warning = "status_update_does_not_execute_task_or_endpoint"
    return {"status": "completed", "task": task.to_dict(), "warnings": [warning]}


def create_progress_review(
    plan_id: str,
    completed_task_ids: list[str] | None = None,
    blocked_task_ids: list[str] | None = None,
    cancelled_task_ids: list[str] | None = None,
    produced_outputs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registry = get_operations_registry()
    plan = registry.get_plan(plan_id)
    if plan is None:
        return {"status": "not_found", "plan_id": plan_id}
    snapshot = build_progress_snapshot(plan, completed_task_ids, blocked_task_ids, cancelled_task_ids, produced_outputs)
    registry.register_progress_snapshot(snapshot)
    return {"status": "completed", "snapshot": snapshot.to_dict(), "obsidian": _sync("sync_progress_snapshot_note", snapshot)}
