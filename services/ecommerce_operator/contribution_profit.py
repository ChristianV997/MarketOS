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


def from_ledger(envelope: CommercialRunEnvelope) -> ContributionProfitResult:
    """Same result shape as reconcile_contribution_profit, but every input
    (campaign revenue by channel, ground-truth revenue, spend, orders,
    refunds, supplier costs) is derived from backend.ledger's replayed
    commerce events for this envelope's workspace instead of the caller
    supplying pre-aggregated scalars. Additive: reconcile_contribution_profit's
    direct-input signature is unchanged for callers who already have real
    numbers in hand. Never raises — an empty/missing ledger degrades to
    an all-zero result (status stays needs_live_data), not a failure.
    """
    campaign_revenue: dict[str, float] = {}
    ground_truth_revenue: float | None = None
    actual_spend = 0.0
    actual_orders = 0
    refunds = 0.0
    supplier_costs = 0.0

    try:
        from backend.ledger.projections import compute_projection
        snapshot = compute_projection(envelope.workspace_id)
        campaign_revenue = dict(snapshot.revenue_by_channel)
        ground_truth_revenue = snapshot.cash_collected if snapshot.order_count else None
        actual_spend = snapshot.total_ad_spend
        actual_orders = snapshot.order_count
        refunds = snapshot.total_refunds
        supplier_costs = snapshot.total_supplier_costs
    except Exception as exc:  # noqa: BLE001
        _log.debug("contribution_profit_from_ledger_projection_failed workspace=%s error=%s",
                   envelope.workspace_id, exc)

    return reconcile_contribution_profit(
        envelope,
        campaign_revenue=campaign_revenue,
        ground_truth_revenue=ground_truth_revenue,
        actual_spend=actual_spend,
        actual_orders=actual_orders,
        refunds=refunds,
        supplier_costs=supplier_costs,
    )
