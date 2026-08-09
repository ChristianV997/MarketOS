"""services.ecommerce_operator.experiment — create_commerce_experiment.

Creates the CommercialRunEnvelope a commerce experiment lives on. Every
prerequisite (validation, unit economics, supplier assumptions, budget
ceiling, kill criteria, attribution method) is stored on envelope.inputs
so evaluate_launch_readiness (launch_guard.py) can check for its presence
without a second schema.
"""
from __future__ import annotations

from typing import Any

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.client_workspace import ClientWorkspace

SERVICE_NAME = "ecommerce_operator"


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def create_commerce_experiment(
    product_name: str,
    *,
    validation: dict[str, Any] | None = None,
    unit_economics: dict[str, Any] | None = None,
    supplier_assumptions: dict[str, Any] | None = None,
    budget_ceiling: float | None = None,
    kill_criteria: dict[str, Any] | None = None,
    attribution_method: str | None = None,
    category: str = "general",
    workspace: ClientWorkspace | None = None,
) -> CommercialRunEnvelope:
    """Never raises. Returns a registered, "created"-status envelope — call
    evaluate_launch_readiness() next before requesting any live action."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()

    resolved_budget_ceiling = budget_ceiling if budget_ceiling is not None else (
        workspace.budget_ceiling_per_experiment or None
    )

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={
            "product_name": product_name,
            "category": category,
            "validation": validation,
            "unit_economics": unit_economics,
            "supplier_assumptions": supplier_assumptions,
            "budget_ceiling": resolved_budget_ceiling,
            "kill_criteria": kill_criteria,
            "attribution_method": attribution_method,
        },
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created", data={"product_name": product_name})
    return envelope
