"""services.product_research.audit — run_product_audit, the paid-service
entrypoint wrapping MarketOS's existing, already-real discovery/validation
pipeline. No new discovery/validation/margin logic lives here.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.experiments.registry import get_experiment_registry
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace

from .schemas import ProductAuditResult

_log = logging.getLogger(__name__)

SERVICE_NAME = "product_research"


def _default_workspace() -> ClientWorkspace:
    return ClientWorkspace(name="ephemeral", workspace_type="internal")


def pricing_breakdown(landed_cost: float, *, second_target_margin_pct: float = 25.0) -> dict[str, Any]:
    """A second suggested price at a different target margin, alongside the
    20%-target price validate_product() already computes — thin re-use of
    suggest_retail_price, no new pricing math."""
    from backend.validation.margin_calculator import suggest_retail_price
    return {
        "target_margin_pct": second_target_margin_pct,
        "suggested_price": suggest_retail_price(landed_cost, target_net_margin_pct=second_target_margin_pct),
    }


def run_product_audit(
    product_name: str,
    *,
    category: str = "general",
    retail_price: float | None = None,
    workspace: ClientWorkspace | None = None,
) -> tuple[ProductAuditResult, CommercialRunEnvelope]:
    """Never raises: every wrapped call already has a fail-silent contract
    (validate_product, discover_products, trend_history, discovery_registry);
    this function additionally guards each with try/except so a surprise
    failure in an optional dependency degrades to a partial result instead
    of aborting the whole audit."""
    workspace = workspace or _default_workspace()
    registry = get_experiment_registry()
    store = ArtifactStore()

    envelope = CommercialRunEnvelope(
        service_name=SERVICE_NAME,
        workspace_id=workspace.workspace_id,
        mode="dry_run" if workspace.dry_run_default else workspace.mode,
        inputs={"product_name": product_name, "category": category, "retail_price": retail_price},
    )
    registry.register(envelope)
    log_transition(envelope, "experiment_created")
    envelope.mark_running()
    log_transition(envelope, "experiment_running")

    validation: dict[str, Any] = {}
    try:
        from backend.validation.validator import validate_product
        validation = validate_product(product_name, retail_price=retail_price, category=category)
    except Exception as exc:  # noqa: BLE001 — never abort the audit
        _log.warning("product_audit_validation_failed product=%s error=%s", product_name, exc)
        validation = {"product": product_name, "recommendation": "red", "risk_flags": ["validation_error"]}

    discovery: dict[str, Any] = {"comparables": []}
    try:
        from backend.discovery import discover_products
        from backend.discovery.trend_history import trend_history
        comparables = discover_products(limit=10)
        discovery["comparables"] = comparables
        discovery["trend_stats"] = trend_history.get_trend_stats(product_name)
    except Exception as exc:  # noqa: BLE001
        _log.debug("product_audit_discovery_context_failed product=%s error=%s", product_name, exc)

    data_provenance: list[dict[str, Any]] = []
    try:
        from backend.discovery.registry import discovery_registry
        data_provenance = discovery_registry.status_report()
    except Exception as exc:  # noqa: BLE001
        _log.debug("product_audit_provenance_failed error=%s", exc)

    pricing: dict[str, Any] = {}
    margin = validation.get("margin")
    if margin:
        try:
            pricing = pricing_breakdown(margin["landed_cost"])
        except Exception as exc:  # noqa: BLE001
            _log.debug("product_audit_pricing_failed error=%s", exc)

    from services.status import commercial_status
    status = commercial_status(workspace=workspace)  # no external credentials/live data needed

    result = ProductAuditResult(
        product_name=product_name,
        category=category,
        discovery=discovery,
        validation=validation,
        supplier=validation.get("supplier"),
        pricing=pricing,
        data_provenance=data_provenance,
        recommendation=validation.get("recommendation", "unknown"),
        dry_run=workspace.dry_run_default,
        status=status,
    )

    try:
        from services.reporting import save_report_artifacts
        from .report import render_product_audit_markdown
        save_report_artifacts(store, workspace.workspace_id, envelope.experiment_id,
                               render_product_audit_markdown(result), result.to_dict())
    except Exception as exc:  # noqa: BLE001 — the JSON result below is the durable fallback
        _log.debug("product_audit_report_save_failed error=%s", exc)
        store.save(workspace.workspace_id, envelope.experiment_id, "result.json", result.to_dict())

    envelope.mark_completed(result.to_dict())
    log_transition(envelope, "experiment_completed")

    return result, envelope
