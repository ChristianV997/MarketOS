from __future__ import annotations

import uuid
from .action_catalog import get_cockpit_action_catalog
from .cockpit_models import CockpitAction
from .cockpit_registry import get_cockpit_registry
from .payload_guard import validate_cockpit_payload_safe
from backend.operations.operations_registry import get_operations_registry

TASK_ACTIONS = {"portfolio_optimization": "generate_optimization", "executive_review": "run_executive_intelligence", "validation_sprint": "run_validation_sprint", "deliverable_generation": "generate_deliverable", "pipeline_refresh": "refresh_pipeline", "refinement": "run_refinement", "source_calibration": "run_source_calibration", "evidence_acquisition": "advisory_manual", "evidence_import": "blocked", "documentation": "advisory_manual", "risk_resolution": "advisory_manual", "manual_review": "advisory_manual"}


def resolve_task_to_cockpit_action(task_id: str) -> CockpitAction:
    task = get_operations_registry().get_task(task_id)
    if task is None: raise ValueError("task_not_found")
    action_type = TASK_ACTIONS.get(task.task_type, "blocked")
    catalog = get_cockpit_action_catalog()
    reasons = list(task.blocker_reasons)
    if task.status in {"blocked", "cancelled", "skipped"}: reasons.append(f"task_status:{task.status}")
    payload = dict(task.safe_payload)
    guard = validate_cockpit_payload_safe(action_type, payload)
    if action_type not in catalog: reasons.append("action_not_allowlisted")
    if not guard["safe"]: reasons.extend(guard["blocked_reasons"])
    if action_type not in {"advisory_manual", "blocked"} and not task.safe_endpoint: reasons.append("missing_safe_endpoint")
    if reasons and action_type not in {"advisory_manual", "blocked"}:
        action_type = "blocked"
    item = CockpitAction(
        f"cockpit_action_{uuid.uuid5(uuid.NAMESPACE_URL, task.task_id).hex[:16]}", task.workspace_id, action_type,
        task.title, task.description, task.task_id, "", task.metadata.get("plan_id", ""), task.safe_endpoint if action_type != "blocked" else "", guard["sanitized_payload"],
        catalog.get(action_type, {}).get("requires_approval", False), "local_operator_approval", "blocked" if action_type == "blocked" else "proposed", sorted(set(reasons)),
        list(task.safety_notes) + ["Resolved from an operating task; endpoint is never dynamically dispatched."], task.expected_outputs, metadata={"task_type": task.task_type, "plan_id": task.metadata.get("plan_id", "")})
    get_cockpit_registry().register_action(item)
    return item


def resolve_plan_to_cockpit_actions(plan_id: str, include_blocked: bool = True):
    tasks = get_operations_registry().list_tasks(plan_id=plan_id, limit=100)
    actions = [resolve_task_to_cockpit_action(task.task_id) for task in sorted(tasks, key=lambda x: x.sequence_order)]
    return actions if include_blocked else [x for x in actions if x.status != "blocked"]
