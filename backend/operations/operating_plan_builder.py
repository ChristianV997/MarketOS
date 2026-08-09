from __future__ import annotations

import time
import uuid
from typing import Any

from backend.optimization.optimization_registry import get_optimization_registry
from backend.optimization.portfolio_actions import PortfolioAction

from .task_models import OperatingPlan, OperatingTask, TaskPacket

ACTION_TO_TASK = {
    "acquire_evidence": "evidence_acquisition",
    "run_refinement_cycle": "refinement",
    "refresh_pipeline": "pipeline_refresh",
    "run_validation_sprint": "validation_sprint",
    "generate_deliverable": "deliverable_generation",
    "run_source_calibration": "source_calibration",
    "resolve_risk": "risk_resolution",
    "hold_opportunity": "manual_review",
    "reject_opportunity": "manual_review",
    "advance_planning": "manual_review",
    "run_executive_cycle": "executive_review",
}

_DEPENDENCIES = {
    "refinement": {"evidence_acquisition", "evidence_import"},
    "pipeline_refresh": {"refinement"},
    "validation_sprint": {"pipeline_refresh"},
    "deliverable_generation": {"validation_sprint"},
    "executive_review": {"source_calibration", "deliverable_generation"},
}


def _id(prefix: str, value: str) -> str:
    return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex[:16]}"


def _task_from_action(action: PortfolioAction, workspace_id: str, index: int) -> OperatingTask:
    task_type = ACTION_TO_TASK.get(action.action_type, "manual_review")
    blocked = list(action.blocked_reasons)
    status = "blocked" if blocked or action.status == "blocked" else "ready"
    checklist = [
        "Review source evidence, provenance, and limitations.",
        "Complete only the referenced local/manual planning step.",
        "Record produced registry IDs or an explicit blocker.",
    ]
    acceptance = [
        "The safe/manual output is recorded in the relevant MarketOS registry.",
        "No external system is called and no spend or mutation occurs.",
    ]
    outputs = [f"{task_type}_result"]
    return OperatingTask(
        task_id=_id("task", action.action_id),
        workspace_id=workspace_id,
        title=action.title,
        description=action.description,
        task_type=task_type,
        status=status,
        priority_score=action.total_action_score,
        simulated_cost=action.estimated_cost,
        estimated_hours=action.estimated_hours,
        sequence_order=index,
        related_action_id=action.action_id,
        related_opportunity_ids=list(action.related_opportunity_ids),
        related_gap_ids=list(action.related_gap_ids),
        related_acquisition_plan_ids=list(action.related_acquisition_plan_ids),
        related_workflow_ids=list(action.related_workflow_ids),
        safe_endpoint=action.safe_endpoint,
        safe_payload=dict(action.safe_payload),
        expected_outputs=outputs,
        acceptance_criteria=acceptance,
        checklist=checklist,
        blocker_reasons=blocked,
        safety_notes=[
            "Planning-only task; an operator must review and perform any manual step.",
            "Do not call external services, spend money, publish, message, order, or mutate commerce systems.",
        ],
        metadata={"action_type": action.action_type, "source_action_status": action.status},
    )


def _assign_dependencies(tasks: list[OperatingTask]) -> None:
    by_type: dict[str, list[OperatingTask]] = {}
    for task in tasks:
        by_type.setdefault(task.task_type, []).append(task)
    for task in tasks:
        dependencies: list[str] = []
        for required_type in _DEPENDENCIES.get(task.task_type, set()):
            dependencies.extend(item.task_id for item in by_type.get(required_type, []) if item.sequence_order < task.sequence_order)
        task.depends_on_task_ids = sorted(set(dependencies))
    by_id = {task.task_id: task for task in tasks}
    for task in tasks:
        for dependency_id in task.depends_on_task_ids:
            if dependency_id in by_id and task.task_id not in by_id[dependency_id].blocks_task_ids:
                by_id[dependency_id].blocks_task_ids.append(task.task_id)


def _assign_days(tasks: list[OperatingTask], capacity: float) -> dict[str, list[str]]:
    day_plan: dict[str, list[str]] = {}
    day = 1
    used = 0.0
    for task in sorted(tasks, key=lambda item: (item.sequence_order, item.task_id)):
        if task.status == "blocked":
            task.due_day = "backlog"
            day_plan.setdefault("backlog", []).append(task.task_id)
            continue
        hours = max(0.0, task.estimated_hours)
        if used and used + hours > capacity:
            day += 1
            used = 0.0
        task.due_day = f"day_{day}"
        day_plan.setdefault(task.due_day, []).append(task.task_id)
        used += hours
    return day_plan


def build_operating_plan_from_optimization(
    workspace_id: str = "default",
    optimization_id: str | None = None,
    horizon: str = "weekly",
    max_tasks: int = 20,
    daily_hour_capacity: float = 4.0,
) -> OperatingPlan:
    max_tasks = max(1, min(int(max_tasks), 100))
    capacity = max(0.25, min(float(daily_hour_capacity), 24.0))
    registry = get_optimization_registry()
    optimization = registry.get_plan(optimization_id) if optimization_id else registry.latest_plan(workspace_id)
    now = time.time()
    if optimization is None:
        setup_actions = [
            PortfolioAction(_id("action", f"{workspace_id}:executive"), workspace_id, "run_executive_cycle", "Establish executive baseline", "Build a local executive intelligence baseline before prioritizing work", estimated_hours=0.5, total_action_score=80, safe_endpoint="/api/intelligence/cycle", safe_payload={"workspace_id": workspace_id}),
            PortfolioAction(_id("action", f"{workspace_id}:optimize"), workspace_id, "run_refinement_cycle", "Establish evidence baseline", "Run a local refinement cycle to identify evidence gaps", estimated_hours=1.0, total_action_score=70, safe_endpoint="/api/discovery/refinement-cycle", safe_payload={"workspace_id": workspace_id}),
        ]
        tasks = [_task_from_action(action, workspace_id, index) for index, action in enumerate(setup_actions, 1)]
        tasks.append(OperatingTask(
            _id("task", f"{workspace_id}:portfolio-optimization"), workspace_id,
            "Build portfolio optimization plan", "Generate deterministic simulated scenarios from the current state.",
            task_type="portfolio_optimization", status="ready", priority_score=75, estimated_hours=0.5,
            safe_endpoint="/api/optimization/portfolio", safe_payload={"workspace_id": workspace_id},
            expected_outputs=["portfolio optimization plan"], checklist=["Review current evidence and constraints", "Generate simulated scenarios", "Record selected planning scenario"],
            acceptance_criteria=["A local optimization plan is persisted", "No real budget or capital is allocated"],
            safety_notes=["Simulation-only; this does not allocate live capital or execute actions."],
            metadata={"setup_plan": True},
        ))
        plan_id = _id("plan", f"{workspace_id}:initial")
        day_plan = _assign_days(tasks, capacity)
        return OperatingPlan(plan_id, workspace_id, "Initial Operating Plan", "Establish a safe planning baseline", horizon, metadata={"setup_plan": True, "planning_only": True}, tasks=tasks, day_plan=day_plan, blocked_task_ids=[task.task_id for task in tasks if task.status == "blocked"], critical_path_task_ids=[task.task_id for task in tasks], estimated_total_hours=sum(task.estimated_hours for task in tasks), simulated_total_cost=sum(task.simulated_cost for task in tasks), expected_outputs=["executive baseline", "evidence gap baseline"], created_at=now, updated_at=now)

    actions = list(optimization.recommended_actions)[:max_tasks]
    tasks = [_task_from_action(action, workspace_id, index) for index, action in enumerate(actions, 1)]
    _assign_dependencies(tasks)
    day_plan = _assign_days(tasks, capacity)
    blocked_ids = [task.task_id for task in tasks if task.status == "blocked"]
    critical = [task.task_id for task in tasks if task.status != "blocked"]
    status = "blocked" if tasks and len(blocked_ids) == len(tasks) else "drafted"
    return OperatingPlan(
        _id("plan", optimization.optimization_id), workspace_id,
        "Weekly MarketOS Operating Plan", "Convert simulated optimization recommendations into operator-ready work", horizon,
        source_optimization_id=optimization.optimization_id,
        source_action_set_id=optimization.action_set_id,
        status=status,
        tasks=tasks, day_plan=day_plan, blocked_task_ids=blocked_ids,
        critical_path_task_ids=critical,
        estimated_total_hours=sum(task.estimated_hours for task in tasks),
        simulated_total_cost=sum(task.simulated_cost for task in tasks),
        expected_outputs=sorted({output for task in tasks for output in task.expected_outputs}),
        created_at=now, updated_at=now,
        metadata={"planning_only": True, "objective": optimization.objective},
    )


def build_task_packets_for_plan(plan: OperatingPlan) -> list[TaskPacket]:
    packets = []
    for task in plan.tasks:
        endpoint = {"endpoint": task.safe_endpoint, "payload": task.safe_payload, "mode": "reference_only"} if task.safe_endpoint else {"mode": "manual_or_advisory_only"}
        instructions = ["Review the task inputs and source provenance."]
        if task.safe_endpoint:
            instructions.append("If appropriate, an operator may call the referenced internal safe endpoint after review; this packet does not execute it.")
        else:
            instructions.append("Complete the manual/local step and record its result in the appropriate registry.")
        packets.append(TaskPacket(
            _id("packet", task.task_id), plan.workspace_id, plan.plan_id, task.task_id,
            task.title, task.description, instructions,
            ["Related IDs and source evidence", "Required local/manual inputs listed on the task"],
            task.expected_outputs, [endpoint], list(task.checklist),
            ["Checklist is complete", "Outputs or blockers are recorded", "No external mutation occurred"],
            list(task.safety_notes), ["If inputs are missing, mark the task blocked and create a refinement/import request."],
            metadata={"related_action_id": task.related_action_id, "plan_id": plan.plan_id},
        ))
    return packets
