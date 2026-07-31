"""services.ecommerce_operator.contribution_profit — reconcile_contribution_profit.

Wraps the existing backend.metrics.attribution.reconcile_revenue (Shopify/
Stripe ground-truth revenue reconciliation) rather than re-deriving revenue
reconciliation logic. contribution_profit is computed from the reconciled
(never platform-inflated) revenue figure, not the raw platform-reported one.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope
from backend.workspaces.artifact_store import ArtifactStore

from .schemas import ContributionProfitResult

_log = logging.getLogger(__name__)


def reconcile_contribution_profit(
    envelope: CommercialRunEnvelope,
    *,
    campaign_revenue: dict[str, float],
    ground_truth_revenue: float | None,
    actual_spend: float = 0.0,
    actual_orders: int = 0,
    refunds: float = 0.0,
    supplier_costs: float = 0.0,
    payment_fees: float = 0.0,
) -> ContributionProfitResult:
    """Never raises: reconcile_revenue is already never-raise; this wraps
    it anyway so a surprise failure degrades to a raw (unreconciled)
    contribution-profit estimate rather than aborting."""
    product_name = (envelope.inputs or {}).get("product_name", "")
    store = ArtifactStore()

    raw_total = sum(max(0.0, v) for v in campaign_revenue.values())
    reconciliation: dict[str, Any] = {}
    revenue_reconciled = raw_total
    try:
        from backend.metrics.attribution import reconcile_revenue
        rec = reconcile_revenue(campaign_revenue, ground_truth_revenue)
        reconciliation = rec.to_dict()
        revenue_reconciled = rec.reconciled_total_revenue
    except Exception as exc:  # noqa: BLE001
        _log.warning("contribution_profit_reconciliation_failed product=%s error=%s", product_name, exc)

    contribution_profit = revenue_reconciled - actual_spend - supplier_costs - payment_fees - refunds
    contribution_margin = (contribution_profit / revenue_reconciled) if revenue_reconciled > 0 else 0.0

    result = ContributionProfitResult(
        product_name=product_name,
        actual_spend=actual_spend,
        actual_revenue_raw=raw_total,
        actual_revenue_reconciled=revenue_reconciled,
        actual_orders=actual_orders,
        refunds=refunds,
        supplier_costs=supplier_costs,
        payment_fees=payment_fees,
        contribution_profit=contribution_profit,
        contribution_margin=contribution_margin,
        reconciliation=reconciliation,
    )

    envelope.actual_spend = actual_spend
    envelope.outputs["contribution_profit_result"] = result.to_dict()
    store.save(envelope.workspace_id, envelope.experiment_id, "contribution_profit.json", result.to_dict())
    log_transition(envelope, "contribution_profit_reconciled", data=result.to_dict())

    return result
