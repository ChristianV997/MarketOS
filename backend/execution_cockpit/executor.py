from __future__ import annotations

import time
import uuid
from typing import Any

from .action_catalog import get_cockpit_action_catalog
from .approval import approval_required_for_action
from .cockpit_models import CockpitAction, CockpitCheckpoint, CockpitExecution
from .cockpit_registry import get_cockpit_registry
from .payload_guard import validate_cockpit_payload_safe
from .summary import build_cockpit_run_summary
from .task_resolver import resolve_plan_to_cockpit_actions


def _checkpoint(execution: CockpitExecution, action: CockpitAction, kind: str, refs=None) -> CockpitCheckpoint:
    item = CockpitCheckpoint(f"checkpoint_{uuid.uuid4().hex[:16]}", execution.workspace_id, execution.execution_id, action.action_id, kind, {"execution_status": execution.status, "action_status": action.status}, refs or [])
    execution.checkpoint_ids.append(item.checkpoint_id); get_cockpit_registry().register_checkpoint(item)
    return item


def _dispatch(action: CockpitAction, payload: dict[str, Any]) -> Any:
    action_type = action.action_type
    if action_type == "generate_optimization":
        from backend.optimization.optimizer import build_portfolio_optimization_plan
        return build_portfolio_optimization_plan(payload.get("workspace_id", action.workspace_id), payload.get("objective", "Optimize next MarketOS actions under resource constraints"), payload.get("constraints"))
    if action_type == "create_operating_plan":
        from backend.operations.operations_runner import create_operating_plan_cycle
        return create_operating_plan_cycle(**payload)
    if action_type == "update_task_status":
        from backend.operations.operations_runner import update_task_status
        return update_task_status(payload["task_id"], payload["status"], payload.get("note", ""), payload.get("produced_outputs"))
    if action_type == "create_progress_review":
        from backend.operations.operations_runner import create_progress_review
        return create_progress_review(payload["plan_id"], payload.get("completed_task_ids"), payload.get("blocked_task_ids"), payload.get("cancelled_task_ids"), payload.get("produced_outputs"))
    if action_type == "run_executive_intelligence":
        from backend.intelligence.executive_command_runner import run_executive_intelligence_cycle
        return run_executive_intelligence_cycle(**payload)
    if action_type == "generate_deliverable":
        from backend.deliverables.product_validation_sprint import build_product_validation_sprint_package
        return build_product_validation_sprint_package(**payload).to_dict()
    if action_type == "run_validation_sprint":
        from backend.discovery.validation_sprint_runner import run_validation_sprint
        return run_validation_sprint(**payload)
    if action_type == "refresh_pipeline":
        from backend.discovery.opportunity_pipeline_builder import refresh_opportunity_pipeline
        return refresh_opportunity_pipeline(**payload)
    if action_type == "run_refinement":
        from backend.discovery.refinement_runner import run_refinement_cycle
        return run_refinement_cycle(**payload)
    if action_type == "run_source_calibration":
        from backend.discovery.source_calibration_engine import run_source_calibration
        result = run_source_calibration(**payload)
        return result.to_dict() if hasattr(result, "to_dict") else result
    if action_type == "run_workflow":
        from backend.workflows.orchestrator import run_workflow
        return run_workflow(**payload)
    if action_type == "resume_workflow":
        from backend.workflows.orchestrator import resume_workflow
        return resume_workflow(payload["workflow_id"], payload.get("from_stage"), payload.get("checkpoint_id"))
    if action_type == "replay_workflow_stage":
        from backend.workflows.orchestrator import replay_workflow_stage
        return replay_workflow_stage(payload["workflow_id"], payload["stage_name"], payload.get("reason", "cockpit_replay"))
    raise ValueError("action_not_dispatchable")


def _refs(value: Any) -> list[dict[str, Any]]:
    if hasattr(value, "to_dict"): value = value.to_dict()
    if not isinstance(value, dict): return []
    refs = []
    keys = {"workflow_id": "workflow", "optimization_id": "optimization_plan", "action_set_id": "action_set", "plan_id": "operating_plan", "task_id": "operating_task", "progress_snapshot_id": "progress_snapshot", "brief_id": "executive_brief", "package_id": "deliverable_package", "sprint_id": "validation_sprint", "snapshot_id": "pipeline_snapshot", "calibration_id": "calibration_run", "analysis_id": "gap_analysis"}
    for key, object_type in keys.items():
        if value.get(key): refs.append({"object_type": object_type, "object_id": value[key], "registry": "marketos", "relation": "produced"})
    for key in ("plan", "brief", "sprint", "package", "snapshot", "optimization_plan"):
        child = value.get(key)
        if isinstance(child, dict): refs.extend(_refs(child))
    return refs


def execute_cockpit_action(action_id: str, approval_id: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    registry = get_cockpit_registry(); action = registry.get_action(action_id)
    if action is None: return {"status": "not_found", "action_id": action_id}
    guard = validate_cockpit_payload_safe(action.action_type, action.safe_payload)
    if action.status in {"blocked", "rejected"} or action.action_type in {"blocked", "advisory_manual"}:
        return {"status": "blocked" if action.action_type == "blocked" else "skipped", "action": action.to_dict(), "blocked_reasons": action.blocked_reasons or ["advisory_manual_action"], "warnings": ["No target was executed."]}
    if not guard["safe"]: return {"status": "blocked", "action": action.to_dict(), "blocked_reasons": guard["blocked_reasons"]}
    approval = registry.get_approval(approval_id) if approval_id else None
    if approval_required_for_action(action) and (approval is None or approval.action_id != action.action_id or approval.decision != "approved"):
        return {"status": "blocked", "action": action.to_dict(), "blocked_reasons": ["approved_matching_approval_required"]}
    execution = CockpitExecution(f"execution_{uuid.uuid4().hex[:16]}", action.workspace_id, action.action_id, action.source_task_id, "created", input_summary={"action_type": action.action_type, "payload_keys": sorted(action.safe_payload)})
    registry.register_execution(execution); _checkpoint(execution, action, "approval" if approval else "before_execution")
    if dry_run:
        execution.status = "completed"; execution.finished_at = time.time(); execution.output_summary = {"preview": True, "target_not_called": True}; _checkpoint(execution, action, "final"); registry.update_execution(execution)
        return {"status": "completed", "dry_run": True, "execution": execution.to_dict(), "warnings": ["Dry-run preview; target callable was not invoked."]}
    action.status = "running"; action.updated_at = time.time(); registry.update_action(action); execution.status = "running"; execution.started_at = time.time(); registry.update_execution(execution)
    try:
        output = _dispatch(action, guard["sanitized_payload"]); refs = _refs(output); execution.status = "completed"; execution.output_summary = output.to_dict() if hasattr(output, "to_dict") else (output if isinstance(output, dict) else {"result": str(output)}); execution.produced_object_ids = refs; execution.finished_at = time.time(); action.status = "completed"; action.updated_at = time.time(); registry.update_action(action); _checkpoint(execution, action, "after_execution", refs)
        if action.source_task_id:
            try:
                from backend.operations.operations_runner import update_task_status
                update_task_status(action.source_task_id, "completed", "Executed through approved local cockpit action.", refs)
            except Exception as exc: execution.warnings.append(f"task_status_update_failed:{exc}")
    except Exception as exc:
        execution.status = "failed"; execution.errors.append(f"{type(exc).__name__}: {exc}"); execution.finished_at = time.time(); action.status = "failed"; action.updated_at = time.time(); registry.update_action(action); _checkpoint(execution, action, "failure")
    registry.update_execution(execution)
    return {"status": execution.status, "execution": execution.to_dict(), "action": action.to_dict()}


def preview_cockpit_plan(plan_id: str) -> dict[str, Any]:
    actions = resolve_plan_to_cockpit_actions(plan_id)
    return {"status": "completed", "plan_id": plan_id, "actions": [x.to_dict() for x in actions], "executable_count": sum(x.status == "proposed" for x in actions), "advisory_count": sum(x.action_type == "advisory_manual" for x in actions), "blocked_count": sum(x.status == "blocked" for x in actions), "warnings": ["Preview only; no approvals or target actions were executed."]}


def execute_cockpit_plan(plan_id: str, task_ids: list[str] | None = None, require_approval: bool = True, dry_run: bool = False, stop_on_failure: bool = False) -> dict[str, Any]:
    from .approval import create_pending_approval
    actions = resolve_plan_to_cockpit_actions(plan_id)
    if task_ids: actions = [x for x in actions if x.source_task_id in set(task_ids)]
    if require_approval and not dry_run:
        pending = []
        for action in actions:
            if action.status == "proposed" and approval_required_for_action(action):
                existing = get_cockpit_registry().list_approvals(action_id=action.action_id, decision="approved", limit=1)
                if not existing: pending.append(create_pending_approval(action).to_dict())
        if pending: return {"status": "pending_approval", "plan_id": plan_id, "actions": [x.to_dict() for x in actions], "pending_approvals": pending, "warnings": ["No action executed while approvals are pending."]}
    executions = []
    for action in actions:
        approval = next(iter(get_cockpit_registry().list_approvals(action_id=action.action_id, decision="approved", limit=1)), None)
        result = execute_cockpit_action(action.action_id, approval.approval_id if approval else None, dry_run)
        if result.get("execution"): executions.append(CockpitExecution.from_dict(result["execution"]))
        if stop_on_failure and result.get("status") == "failed": break
    summary = build_cockpit_run_summary(plan_id, executions, actions); get_cockpit_registry().register_summary(summary)
    try:
        from backend.operations.operations_runner import create_progress_review
        progress = create_progress_review(plan_id, [a.source_task_id for a in actions if a.status == "completed"], [a.source_task_id for a in actions if a.status == "blocked"], produced_outputs=summary.produced_outputs)
        summary.progress_snapshot_id = progress.get("snapshot", {}).get("snapshot_id", ""); get_cockpit_registry().register_summary(summary)
    except Exception: pass
    return {"status": "completed", "summary": summary.to_dict(), "executions": [x.to_dict() for x in executions], "actions": [x.to_dict() for x in actions]}
