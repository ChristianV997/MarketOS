from __future__ import annotations

import time
import uuid
from typing import Any

from .failure_classifier import classify_workflow_failure
from .runbook import get_workflow_runbook
from .stage_executor import execute_workflow_stage
from .workflow_models import (
    WorkflowCheckpoint,
    WorkflowRun,
    WorkflowStage,
    WorkflowTimelineEvent,
)
from .workflow_registry import get_workflow_registry
from .workflow_safety import validate_workflow_payload_safe
from .workflow_summary import build_workflow_summary

# Only workflow-level markers are de-duplicated. Stage events are never repeated
# by re-entry (finished stages are skipped), so a stage_* event is always a real
# new attempt and must be recorded.
_IDEMPOTENT_EVENTS = frozenset({"workflow_created", "workflow_completed", "workflow_partial"})

# Workflow-level warnings persist across runs; stage warnings are
# re-aggregated from stages in _sync_run_state so retried stages
# do not carry stale warnings.

_WORKFLOW_LEVEL_WARNING_PREFIXES = (
    "resumed_from_checkpoint:",
    "resume_checkpoint_ignored:",
    "recovery_from_stage:",
)


# Workflow-level warnings persist across runs; stage warnings are
# re-aggregated from stages in _sync_run_state so retried stages
# do not carry stale warnings.

_WORKFLOW_LEVEL_WARNING_PREFIXES = (
    "resumed_from_checkpoint:",
    "resume_checkpoint_ignored:",
    "recovery_from_stage:",
)



def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def build_default_stage_plan(workflow_type: str, payload: dict[str, Any] | None = None) -> list[WorkflowStage]:
    """Build a fresh stage plan from the registered, safe runbook."""
    return [
        WorkflowStage(_id("stage"), stage_name, index)
        for index, stage_name in enumerate(get_workflow_runbook(workflow_type).stages, start=1)
    ]


def _event(
    run: WorkflowRun,
    stage_name: str,
    event_type: str,
    message: str,
    severity: str = "info",
    refs: list[dict[str, Any]] | None = None,
) -> WorkflowTimelineEvent:
    if event_type in _IDEMPOTENT_EVENTS:
        for existing in get_workflow_registry().list_timeline(run.workflow_id):
            if existing.stage_name == stage_name and existing.event_type == event_type:
                return existing
    event = WorkflowTimelineEvent(
        _id("event"),
        run.workflow_id,
        run.workspace_id,
        stage_name,
        event_type,
        message,
        severity,
        refs or [],
    )
    get_workflow_registry().register_timeline_event(event)
    return event


def _checkpoint(
    run: WorkflowRun,
    stage: WorkflowStage,
    checkpoint_type: str,
    recoverable: bool = True,
    replayable: bool = True,
) -> WorkflowCheckpoint:
    checkpoint = WorkflowCheckpoint(
        _id("checkpoint"),
        run.workflow_id,
        stage.stage_name,
        stage.status,
        checkpoint_type,
        {"workflow_status": run.status, "current_stage": run.current_stage},
        list(stage.produced_object_ids),
        recoverable,
        replayable,
        metadata={"stage_order": stage.order},
    )
    run.checkpoints.append(checkpoint)
    get_workflow_registry().register_checkpoint(checkpoint)
    _event(run, stage.stage_name, "checkpoint_created", f"Checkpoint {checkpoint_type} created", refs=checkpoint.produced_object_ids)
    return checkpoint


def _persist(run: WorkflowRun) -> None:
    get_workflow_registry().update_workflow(run)


def _checkpoint_owner_error(
    registry: Any,
    checkpoint: WorkflowCheckpoint,
    *,
    workspace_id: str,
    workflow_id: str | None = None,
) -> str | None:
    """Reject checkpoints whose persisted owner is outside the requested scope."""
    if workflow_id is not None and checkpoint.workflow_id != workflow_id:
        return "checkpoint_workflow_mismatch"
    owner = registry.get_workflow(checkpoint.workflow_id)
    if owner is None:
        return "checkpoint_owner_not_found"
    if owner.workspace_id != workspace_id:
        return "checkpoint_workspace_mismatch"
    if not any(
        item.checkpoint_id == checkpoint.checkpoint_id
        and item.workflow_id == owner.workflow_id
        for item in owner.checkpoints
    ):
        return "checkpoint_owner_mismatch"
    return None


def _sync_run_state(run: WorkflowRun) -> None:
    seen_refs: set[tuple[Any, ...]] = set()
    aggregated_refs: list[dict[str, Any]] = []
    for s in run.stages:
        for ref in s.produced_object_ids:
            key = (ref.get("object_type"), ref.get("object_id"), ref.get("relation"))
            if key not in seen_refs:
                seen_refs.add(key)
                aggregated_refs.append(ref)
    run.produced_object_ids = aggregated_refs

    # Workflow-level markers (resume/recovery notes) survive; stage-derived
    # warnings are re-aggregated from stages only, so a retried stage that
    # succeeds no longer carries its previous attempt's warnings.
    active_warnings: list[str] = []
    for w in run.warnings:
        if w.startswith(_WORKFLOW_LEVEL_WARNING_PREFIXES) and w not in active_warnings:
            active_warnings.append(w)
    for s in run.stages:
        for w in s.warnings:
            if w not in active_warnings:
                active_warnings.append(w)
    run.warnings = active_warnings

    active_errors: list[str] = []
    for s in run.stages:
        if s.status in {"failed", "blocked"}:
            for err in (s.errors or s.blocked_reasons):
                if err not in active_errors:
                    active_errors.append(err)
    if run.status in {"blocked", "failed"} and not active_errors:
        active_errors = list(dict.fromkeys(run.errors))
    run.errors = active_errors

def _context_from_run(run: WorkflowRun) -> dict[str, Any]:
    """Return a conservative context for recovery.

    Stage outputs are reloaded from their durable registries by the stage
    implementations. We intentionally do not serialize arbitrary service
    objects into a workflow record.
    """
    return {}


def _execute_stages(
    run: WorkflowRun,
    start_index: int = 0,
    stop_after_stage: str | None = None,
    context: dict[str, Any] | None = None,
    force_start_stage: bool = False,
) -> WorkflowRun:
    context = context or _context_from_run(run)
    run.status = "running"
    run.started_at = run.started_at or time.time()
    _persist(run)

    for index in range(start_index, len(run.stages)):
        stage = run.stages[index]
        # Completed work is idempotent: interrupt/restart/replay must not
        # re-enter a finished stage or emit another transition. force_start
        # still re-runs failed/blocked/pending stages.
        if stage.status in {"completed", "skipped", "recovered"}:
            if stop_after_stage == stage.stage_name:
                break
            continue

        run.current_stage = stage.stage_name
        stage.status = "running"
        stage.started_at = time.time()
        stage.finished_at = None
        stage.errors = []
        stage.metadata.pop("failure_classification", None)
        stage.input_summary = {"keys": sorted(run.input_payload)}
        _event(run, stage.stage_name, "stage_started", "Stage started")
        _checkpoint(run, stage, "before_stage")
        _persist(run)

        try:
            result = execute_workflow_stage(run, stage, context)
            stage.status = result.get("status", "completed")
            stage.warnings = list(result.get("warnings", []))
            stage.errors = list(result.get("errors", []))
            stage.blocked_reasons = list(result.get("blocked_reasons", []))
            stage.output_summary = {"status": stage.status}
            stage.produced_object_ids = list(result.get("produced_object_ids", []))
            context.update(result.get("next_context", {}))

            if stage.status in {"blocked", "failed"}:
                run.status = "partial"
                event_type = "stage_blocked" if stage.status == "blocked" else "stage_failed"
                _event(run, stage.stage_name, event_type, "; ".join(stage.blocked_reasons or stage.errors) or "Stage did not complete", "warning")
            elif stage.status == "skipped":
                _event(run, stage.stage_name, "stage_skipped", "; ".join(stage.warnings) or "Stage skipped", "warning")
            else:
                _event(run, stage.stage_name, "stage_completed", "Stage completed", refs=stage.produced_object_ids)
        except Exception as exc:  # stage boundaries are intentionally never-raise
            info = classify_workflow_failure(stage.stage_name, exc)
            stage.status = "failed"
            stage.errors.append(info["message"])
            stage.metadata["failure_classification"] = info
            run.status = "partial"
            _event(run, stage.stage_name, "stage_failed", info["message"], info["severity"])

        stage.finished_at = time.time()
        classification = stage.metadata.get("failure_classification")
        if classification:
            is_safety = classification.get("category") in {"blocked_by_safety", "unsafe_path"}
            recoverable = False if is_safety else bool(classification.get("recoverable", False))
            replayable = False if (is_safety or stage.status == "blocked") else True
        elif stage.status in {"failed", "blocked"}:
            recoverable = False
            replayable = stage.status != "blocked"
        else:
            recoverable = True
            replayable = True

        _checkpoint(
            run,
            stage,
            "failure" if stage.status in {"failed", "blocked"} else "after_stage",
            recoverable=recoverable,
            replayable=replayable,
        )
        _sync_run_state(run)
        _persist(run)
        if stop_after_stage == stage.stage_name:
            break

    finished_orders = [stage.order for stage in run.stages if stage.finished_at]
    all_finished = bool(finished_orders) and len(finished_orders) == len(run.stages)
    has_failure = any(stage.status in {"failed", "blocked"} for stage in run.stages if stage.finished_at)
    run.status = "partial" if has_failure or not all_finished else "completed"
    run.finished_at = time.time()
    _sync_run_state(run)
    run.final_output = build_workflow_summary(run)
    _persist(run)
    _event(run, "", "workflow_completed" if run.status == "completed" else "workflow_partial", f"Workflow {run.status}")
    return run


def _sync_workflow_notes(run: WorkflowRun) -> dict[str, Any]:
    try:
        from backend.obsidian.sync import sync_workflow_run_note, sync_workflow_timeline_note

        registry = get_workflow_registry()
        return {
            "run": sync_workflow_run_note(run),
            "timeline": sync_workflow_timeline_note(run, registry.list_timeline(run.workflow_id)),
        }
    except Exception as exc:
        return {"status": "warning", "warnings": [f"obsidian_sync_failed: {exc}"]}


def run_workflow(
    workspace_id: str = "default",
    workflow_type: str = "full_market_cycle",
    title: str | None = None,
    objective: str | None = None,
    payload: dict[str, Any] | None = None,
    resume_from_checkpoint_id: str | None = None,
    stop_after_stage: str | None = None,
) -> dict[str, Any]:
    payload = dict(payload or {})
    safety = validate_workflow_payload_safe(payload)
    run = WorkflowRun(
        _id("workflow"),
        workspace_id,
        workflow_type,
        title or workflow_type.replace("_", " ").title(),
        objective or "Run safe MarketOS workflow",
        input_payload=safety["sanitized_payload"],
        safety_flags=list(safety["blocked_reasons"]),
    )
    registry = get_workflow_registry()
    registry.register_workflow(run)
    _event(run, "", "workflow_created", "Workflow created")

    if not safety["safe"]:
        run.status = "blocked"
        run.errors = list(safety["blocked_reasons"])
        run.warnings = list(safety["warnings"])
        run.final_output = build_workflow_summary(run)
        _event(run, "", "workflow_failed", "Workflow blocked by safety guard", "critical")
        _persist(run)
        return run.to_dict()

    try:
        run.stages = build_default_stage_plan(workflow_type, payload)
    except Exception as exc:
        info = classify_workflow_failure("plan", exc)
        run.status = "failed"
        run.errors.append(info["message"])
        run.final_output = build_workflow_summary(run)
        _event(run, "", "workflow_failed", info["message"], info["severity"])
        _persist(run)
        return run.to_dict()

    start_index = 0
    if resume_from_checkpoint_id:
        checkpoint = registry.checkpoints.get(resume_from_checkpoint_id)
        if checkpoint is None:
            checkpoint = next((item for item in run.checkpoints if item.checkpoint_id == resume_from_checkpoint_id), None)
        if checkpoint is None:
            run.warnings.append("resume_checkpoint_ignored: checkpoint not found")
        else:
            owner_error = _checkpoint_owner_error(
                registry,
                checkpoint,
                workspace_id=run.workspace_id,
            )
            if owner_error is not None:
                run.status = "blocked"
                run.errors.append(f"resume_checkpoint_rejected:{owner_error}")
                run.final_output = build_workflow_summary(run)
                _event(run, "", "workflow_failed", "Checkpoint ownership validation failed", "critical")
                _persist(run)
                return run.to_dict()
        if checkpoint is not None and not checkpoint.recoverable:
            run.warnings.append("resume_checkpoint_ignored: checkpoint not recoverable")
        elif checkpoint is not None:
            matching_index = next((idx for idx, s in enumerate(run.stages) if s.stage_name == checkpoint.stage_name), None)
            if matching_index is not None:
                start_index = matching_index
                run.warnings.append(f"resumed_from_checkpoint:{checkpoint.checkpoint_id}")
            else:
                run.warnings.append("resume_checkpoint_ignored: stage not in plan")
    completed = _execute_stages(run, start_index, stop_after_stage, force_start_stage=bool(resume_from_checkpoint_id and start_index > 0))
    result = completed.to_dict()
    result["obsidian"] = _sync_workflow_notes(completed)
    return result


def resume_workflow(
    workflow_id: str,
    from_stage: str | None = None,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    registry = get_workflow_registry()
    run = registry.get_workflow(workflow_id)
    if run is None:
        return {"status": "not_found", "workflow_id": workflow_id}

    stage_name = from_stage
    if checkpoint_id:
        checkpoint = next((item for item in run.checkpoints if item.checkpoint_id == checkpoint_id), None)
        if checkpoint is None:
            checkpoint = registry.checkpoints.get(checkpoint_id)
        if checkpoint is None:
            return {"status": "not_found", "workflow_id": workflow_id, "checkpoint_id": checkpoint_id}
        owner_error = _checkpoint_owner_error(
            registry,
            checkpoint,
            workspace_id=run.workspace_id,
            workflow_id=workflow_id,
        )
        if owner_error is not None:
            return {
                "status": "blocked",
                "workflow_id": workflow_id,
                "checkpoint_id": checkpoint_id,
                "blocked_reasons": [owner_error],
            }
        if not checkpoint.recoverable:
            return {"status": "blocked", "workflow_id": workflow_id, "blocked_reasons": ["checkpoint_not_recoverable"]}
        stage_name = checkpoint.stage_name
    if not stage_name:
        stage_name = run.current_stage or next((item.stage_name for item in run.stages if item.status not in {"completed", "skipped", "recovered"}), "")
    stage_index = next((index for index, item in enumerate(run.stages) if item.stage_name == stage_name), None)
    if stage_index is None:
        return {"status": "not_found", "workflow_id": workflow_id, "stage_name": stage_name}

    _event(run, stage_name, "recovery_started", "Workflow recovery started")
    run.warnings.append(f"recovery_from_stage:{stage_name}")
    recovered = _execute_stages(run, stage_index, force_start_stage=True)
    _event(run, stage_name, "recovery_completed", "Workflow recovery completed")
    result = recovered.to_dict()
    result["obsidian"] = _sync_workflow_notes(recovered)
    return result


def replay_workflow_stage(workflow_id: str, stage_name: str, reason: str = "manual_replay") -> dict[str, Any]:
    registry = get_workflow_registry()
    run = registry.get_workflow(workflow_id)
    if run is None:
        return {"status": "not_found", "workflow_id": workflow_id}
    if stage_name in {"final_summary", "executive_intelligence"}:
        return {"status": "blocked", "workflow_id": workflow_id, "blocked_reasons": ["stage_replay_requires_full_safe_rerun"]}
    stage = next((item for item in run.stages if item.stage_name == stage_name), None)
    if stage is None:
        return {"status": "not_found", "workflow_id": workflow_id, "stage_name": stage_name}
    checkpoint = registry.latest_checkpoint(workflow_id, stage_name)
    if checkpoint is not None and not checkpoint.replayable:
        return {"status": "blocked", "workflow_id": workflow_id, "blocked_reasons": ["stage_checkpoint_not_replayable"]}

    _event(run, stage_name, "replay_started", reason)
    _checkpoint(run, stage, "replay", recoverable=True, replayable=True)
    stage.retry_count += 1
    stage.metadata["replay_reason"] = reason
    # Replay only the requested stage on the existing run. Existing refs remain
    # intact; new refs are marked as replay output by the stage metadata.
    replayed = _execute_stages(run, run.stages.index(stage), stage_name)
    # Tag copies: earlier timeline events and checkpoints share the original ref dicts.
    stage.produced_object_ids = [{**ref, "relation": "replay_of"} for ref in stage.produced_object_ids]
    _sync_run_state(replayed)
    replayed.final_output = build_workflow_summary(replayed)
    replayed.final_output = build_workflow_summary(replayed)
    _event(replayed, stage_name, "replay_completed", "Workflow stage replay completed", refs=stage.produced_object_ids)
    result = replayed.to_dict()
    result["obsidian"] = _sync_workflow_notes(replayed)
    return result
