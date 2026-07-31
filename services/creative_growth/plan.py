"""services.creative_growth.plan — recommend_next_creative_batch and the
top-level build_creative_growth_plan entrypoint."""
from __future__ import annotations

from typing import Any

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace

from .content_calendar_report import build_content_calendar
from .fatigue_report import analyze_creative_fatigue
from .hooks import generate_ad_angles, generate_hook_matrix
from .schemas import CreativeGrowthPlan
from .ugc_plan import generate_ugc_briefs

SERVICE_NAME = "creative_growth"


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def recommend_next_creative_batch(
    hooks: list[str], angles: list[str], fatigue_report: dict[str, Any], *, n: int = 3,
) -> dict[str, Any]:
    """Never raises. Recommends what to test next: fresh (non-fatigued)
    hooks/angles first; if everything is fatigued, recommends a full
    refresh batch rather than silently reusing decayed creative."""
    fatigued_hooks = set(fatigue_report.get("fatigued_hooks", []))
    fatigued_angles = set(fatigue_report.get("fatigued_angles", []))

    fresh_hooks = [h for h in hooks if h not in fatigued_hooks][:n]
    fresh_angles = [a for a in angles if a not in fatigued_angles][:n]

    if not fresh_hooks and not fresh_angles and (hooks or angles):
        return {
            "action": "full_refresh",
            "reason": "every current hook and angle is fatigued — generate net-new creative, don't reuse decayed variants",
            "hooks_to_test": [],
            "angles_to_test": [],
        }

    return {
        "action": "test_fresh_batch",
        "reason": f"{len(fresh_hooks)} hooks and {len(fresh_angles)} angles not yet fatigued",
        "hooks_to_test": fresh_hooks,
        "angles_to_test": fresh_angles,
    }


def build_creative_growth_plan(
    product_name: str,
    *,
    category: str = "general",
    signals: list[dict[str, Any]] | None = None,
    workspace: ClientWorkspace | None = None,
) -> tuple[CreativeGrowthPlan, CommercialRunEnvelope]:
    """Never raises: composes every function above; each is already
    individually fail-soft."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()
    store = ArtifactStore()

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={"product_name": product_name, "category": category},
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()

    angles = generate_ad_angles(product_name, signals=signals)
    hook_matrix = generate_hook_matrix(product_name, angles)
    hooks = list(dict.fromkeys(row["hook"] for row in hook_matrix))
    ugc_briefs = generate_ugc_briefs(product_name, angles)
    calendar = build_content_calendar(product_name, briefs=ugc_briefs)
    fatigue = analyze_creative_fatigue(hooks, angles)
    next_batch = recommend_next_creative_batch(hooks, angles, fatigue)

    result = CreativeGrowthPlan(
        product_name=product_name,
        category=category,
        hooks=hooks,
        angles=angles,
        hook_matrix=hook_matrix,
        ugc_briefs=ugc_briefs,
        content_calendar=calendar,
        fatigue_report=fatigue,
        next_batch_recommendation=next_batch,
        dry_run=workspace.dry_run_default,
    )

    store.save(workspace.workspace_id, envelope.experiment_id, "result.json", result.to_dict())
    envelope.mark_completed(result.to_dict())
    log_transition(envelope, "experiment_completed")

    return result, envelope
