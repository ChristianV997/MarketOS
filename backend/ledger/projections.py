"""backend.ledger.projections — replay backend.ledger.events into derived
commerce numbers, scoped per workspace_id.

This is the *only* place in backend.ledger that computes anything. It
never invents new margin/attribution math: recognized revenue, cash
collected, and contribution profit are plain sums over the replayed
event stream; CAC and per-{order,product,channel} profit are ratios over
those sums. Where MarketOS already has a more sophisticated calculation
for a related number (category-aware returns, LTV-adjusted CAC), that
lives in backend.validation.margin_calculator / backend.economics.ltv —
services.unit_economics.from_ledger() and
services.ecommerce_operator.contribution_profit.from_ledger() compose
this module's derived scalars with those existing calculators rather
than duplicating them here.

``cash_conversion_cycle_days`` is a deliberately simplified proxy —
average days between order creation and payment capture — not the full
DIO+DSO-DPO formula, since this ledger doesn't track inventory-holding or
accounts-payable events. Documented here, not silently overstated.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration.event_store import event_store

from .events import EVENT_TYPES


def _events_for_workspace(workspace_id: str, event_type: str) -> list[dict]:
    return [
        e for e in event_store.events_of_type(event_type)
        if (e.get("data") or {}).get("workspace_id") == workspace_id
    ]


def raw_events_for_workspace(workspace_id: str) -> dict[str, list[dict]]:
    """All ledger events for *workspace_id*, grouped by event type — the
    replay input every projection below is derived from."""
    return {et: _events_for_workspace(workspace_id, et) for et in EVENT_TYPES}


@dataclass
class LedgerSnapshot:
    workspace_id: str
    order_count: int = 0
    canceled_order_count: int = 0
    recognized_revenue: float = 0.0
    cash_collected: float = 0.0
    total_supplier_costs: float = 0.0
    total_ad_spend: float = 0.0
    total_refunds: float = 0.0
    total_chargebacks: float = 0.0
    gross_profit: float = 0.0
    contribution_profit: float = 0.0
    contribution_margin: float = 0.0
    cac_blended: float = 0.0
    cac_by_channel: dict[str, float] = field(default_factory=dict)
    profit_per_order: float = 0.0
    profit_per_product: dict[str, float] = field(default_factory=dict)
    profit_per_channel: dict[str, float] = field(default_factory=dict)
    revenue_by_channel: dict[str, float] = field(default_factory=dict)
    cash_conversion_cycle_days: float | None = None
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "order_count": self.order_count,
            "canceled_order_count": self.canceled_order_count,
            "recognized_revenue": round(self.recognized_revenue, 2),
            "cash_collected": round(self.cash_collected, 2),
            "total_supplier_costs": round(self.total_supplier_costs, 2),
            "total_ad_spend": round(self.total_ad_spend, 2),
            "total_refunds": round(self.total_refunds, 2),
            "total_chargebacks": round(self.total_chargebacks, 2),
            "gross_profit": round(self.gross_profit, 2),
            "contribution_profit": round(self.contribution_profit, 2),
            "contribution_margin": round(self.contribution_margin, 4),
            "cac_blended": round(self.cac_blended, 2),
            "cac_by_channel": {k: round(v, 2) for k, v in self.cac_by_channel.items()},
            "profit_per_order": round(self.profit_per_order, 2),
            "profit_per_product": {k: round(v, 2) for k, v in self.profit_per_product.items()},
            "profit_per_channel": {k: round(v, 2) for k, v in self.profit_per_channel.items()},
            "revenue_by_channel": {k: round(v, 2) for k, v in self.revenue_by_channel.items()},
            "cash_conversion_cycle_days": (
                round(self.cash_conversion_cycle_days, 2)
                if self.cash_conversion_cycle_days is not None else None),
            "generated_at": self.generated_at,
        }


def compute_projection(workspace_id: str) -> LedgerSnapshot:
    """Replay every ledger event for *workspace_id* into a LedgerSnapshot.

    Never raises: an unreadable/missing event log simply yields an
    all-zero snapshot (event_store.tail-style reads already swallow
    per-line JSON errors; there is no further failure mode here).
    """
    events = raw_events_for_workspace(workspace_id)

    orders = {e["data"]["order_id"]: e["data"] for e in events["OrderCreated"] if e.get("data", {}).get("order_id")}
    canceled_ids = {e["data"]["order_id"] for e in events["OrderCanceled"] if e.get("data", {}).get("order_id")}

    active_orders = {oid: o for oid, o in orders.items() if oid not in canceled_ids}

    recognized_revenue = sum(o.get("revenue", 0.0) for o in active_orders.values())

    payments = events["PaymentCaptured"]
    cash_captured = sum(e["data"].get("amount", 0.0) for e in payments)
    refunds = events["RefundIssued"]
    total_refunds = sum(e["data"].get("amount", 0.0) for e in refunds)
    chargebacks = events["ChargebackOpened"]
    total_chargebacks = sum(e["data"].get("amount", 0.0) for e in chargebacks)
    cash_collected = cash_captured - total_refunds - total_chargebacks

    supplier_costs = events["SupplierCostObserved"]
    total_supplier_costs = sum(
        e["data"].get("amount", 0.0) for e in supplier_costs
        if e["data"].get("order_id") not in canceled_ids
    )

    ad_spend_events = events["AdSpendObserved"]
    total_ad_spend = sum(e["data"].get("amount", 0.0) for e in ad_spend_events)
    ad_spend_by_channel: dict[str, float] = {}
    for e in ad_spend_events:
        ch = e["data"].get("channel") or "unknown"
        ad_spend_by_channel[ch] = ad_spend_by_channel.get(ch, 0.0) + e["data"].get("amount", 0.0)

    gross_profit = recognized_revenue - total_supplier_costs
    contribution_profit = gross_profit - total_ad_spend - total_refunds - total_chargebacks
    contribution_margin = (contribution_profit / recognized_revenue) if recognized_revenue > 0 else 0.0

    order_count = len(active_orders)
    cac_blended = (total_ad_spend / order_count) if order_count else 0.0

    # Attribution claims map each order to the channel that gets credit —
    # used both for per-channel CAC and per-channel profit; an order with
    # no claim falls back to whatever channel it was created with (if any).
    attribution = events["AttributionClaimObserved"]
    order_channel: dict[str, str] = {
        oid: o.get("channel", "") for oid, o in active_orders.items() if o.get("channel")
    }
    for e in attribution:
        oid = e["data"].get("order_id")
        if oid in active_orders and e["data"].get("channel"):
            order_channel[oid] = e["data"]["channel"]

    orders_per_channel: dict[str, int] = {}
    for oid in active_orders:
        ch = order_channel.get(oid, "unknown")
        orders_per_channel[ch] = orders_per_channel.get(ch, 0) + 1

    cac_by_channel = {
        ch: (ad_spend_by_channel.get(ch, 0.0) / count) if count else 0.0
        for ch, count in orders_per_channel.items()
    }

    profit_per_order = (contribution_profit / order_count) if order_count else 0.0

    profit_per_product: dict[str, float] = {}
    revenue_by_product: dict[str, float] = {}
    cost_by_product: dict[str, float] = {}
    for o in active_orders.values():
        pname = o.get("product_name") or "unknown"
        revenue_by_product[pname] = revenue_by_product.get(pname, 0.0) + o.get("revenue", 0.0)
    for e in supplier_costs:
        if e["data"].get("order_id") in canceled_ids:
            continue
        pname = e["data"].get("product_name") or "unknown"
        cost_by_product[pname] = cost_by_product.get(pname, 0.0) + e["data"].get("amount", 0.0)
    for pname in set(revenue_by_product) | set(cost_by_product):
        profit_per_product[pname] = revenue_by_product.get(pname, 0.0) - cost_by_product.get(pname, 0.0)

    profit_per_channel: dict[str, float] = {}
    revenue_by_channel: dict[str, float] = {}
    for oid, o in active_orders.items():
        ch = order_channel.get(oid, "unknown")
        revenue_by_channel[ch] = revenue_by_channel.get(ch, 0.0) + o.get("revenue", 0.0)
    for ch in set(revenue_by_channel) | set(ad_spend_by_channel):
        profit_per_channel[ch] = revenue_by_channel.get(ch, 0.0) - ad_spend_by_channel.get(ch, 0.0)

    # Cash conversion cycle proxy: avg days between order creation and
    # payment capture, only for orders with a matched payment event.
    payment_ts_by_order: dict[str, float] = {}
    for e in payments:
        oid = e["data"].get("order_id")
        if oid:
            payment_ts_by_order[oid] = e["data"].get("ts", e.get("ts", 0.0))
    lags = [
        payment_ts_by_order[oid] - o.get("ts", 0.0)
        for oid, o in active_orders.items()
        if oid in payment_ts_by_order and payment_ts_by_order[oid] >= o.get("ts", 0.0)
    ]
    ccc_days = (sum(lags) / len(lags) / 86_400.0) if lags else None

    return LedgerSnapshot(
        workspace_id=workspace_id,
        order_count=order_count,
        canceled_order_count=len(canceled_ids),
        recognized_revenue=recognized_revenue,
        cash_collected=cash_collected,
        total_supplier_costs=total_supplier_costs,
        total_ad_spend=total_ad_spend,
        total_refunds=total_refunds,
        total_chargebacks=total_chargebacks,
        gross_profit=gross_profit,
        contribution_profit=contribution_profit,
        contribution_margin=contribution_margin,
        cac_blended=cac_blended,
        cac_by_channel=cac_by_channel,
        profit_per_order=profit_per_order,
        profit_per_product=profit_per_product,
        profit_per_channel=profit_per_channel,
        revenue_by_channel=revenue_by_channel,
        cash_conversion_cycle_days=ccc_days,
    )
