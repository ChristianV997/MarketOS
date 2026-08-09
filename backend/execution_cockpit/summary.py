from __future__ import annotations

import uuid
from .cockpit_models import CockpitAction, CockpitExecution, CockpitRunSummary


def build_cockpit_run_summary(plan_id: str, executions: list[CockpitExecution], actions: list[CockpitAction]) -> CockpitRunSummary:
    by_action = {item.action_id: item for item in actions}
    outputs = [ref for execution in executions for ref in execution.produced_object_ids]
    completed = sum(x.status == "completed" for x in executions)
    blocked = sum(x.status == "blocked" for x in executions) + sum(x.status == "blocked" for x in actions if x.action_id not in by_action or x.action_id not in {e.action_id for e in executions})
    failed = sum(x.status == "failed" for x in executions)
    skipped = sum(x.status == "skipped" for x in executions)
    next_actions = []
    if blocked: next_actions.append("Review blocked actions and resolve their explicit blockers before approval.")
    if failed: next_actions.append("Inspect failed execution checkpoints; replay only an explicitly safe action after review.")
    if completed: next_actions.append("Review produced registry IDs and create an operations progress review.")
    if not next_actions: next_actions.append("Review the plan and decide whether additional local evidence or refinement is needed.")
    return CockpitRunSummary(f"cockpit_summary_{uuid.uuid4().hex[:16]}", actions[0].workspace_id if actions else "default", plan_id, [x.execution_id for x in executions], completed, blocked, failed, skipped, outputs, "", next_actions)


def build_operator_execution_brief(summary: CockpitRunSummary) -> str:
    return summary.to_markdown() + "\n\nReview approval records, checkpoints, and task status before any further operator action.\n"
