"""Summary projection for MarketOS workflow runs."""
from __future__ import annotations

from typing import Any


def build_workflow_summary(run: Any) -> dict[str, Any]:
    stages = run.stages
    completed = [x.stage_name for x in stages if x.status in {"completed", "recovered"}]
    blocked = [x.stage_name for x in stages if x.status == "blocked"]
    failed = [x.stage_name for x in stages if x.status == "failed"]
    skipped = [x.stage_name for x in stages if x.status == "skipped"]

    actions: list[str] = []
    if blocked or failed:
        actions.append("Review blocked/failed stages and resume from a recoverable checkpoint.")
    if not completed:
        actions.append("Provide safe local evidence inputs and rerun the workflow.")

    for stage in stages:
        if stage.status in {"failed", "blocked"}:
            fc = stage.metadata.get("failure_classification") or {}
            for item in fc.get("next_actions", []):
                if item not in actions:
                    actions.append(item)

    return {
        "summary": f"Workflow `{run.title}` is `{run.status}` with {len(completed)} completed stage(s).",
        "status": run.status,
        "completed_stages": completed,
        "blocked_stages": blocked,
        "failed_stages": failed,
        "skipped_stages": skipped,
        "produced_artifacts": run.produced_object_ids,
        "key_outputs": run.final_output,
        "next_actions": actions,
        "operator_actions_required": run.errors + run.warnings,
        "safety_notes": ["Synchronous dry-run workflow; no live external action is permitted."],
        "recovery_options": [
            "Resume from the latest recoverable checkpoint.",
            "Replay only a safe replayable stage.",
        ],
    }
