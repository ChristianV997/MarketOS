"""Tests for backend.ledger.projections — hand-computed cross-checks."""
import uuid

from backend.ledger.events import (
    record_ad_spend_observed,
    record_attribution_claim_observed,
    record_order_canceled,
    record_order_created,
    record_payment_captured,
    record_refund_issued,
    record_supplier_cost_observed,
)
from backend.ledger.projections import compute_projection


def _ws() -> str:
    return f"ws-ledger-proj-{uuid.uuid4().hex[:8]}"


def test_compute_projection_empty_workspace_is_all_zero():
    snap = compute_projection(_ws())
    assert snap.order_count == 0
    assert snap.recognized_revenue == 0.0
    assert snap.contribution_profit == 0.0
    assert snap.cash_conversion_cycle_days is None


def test_compute_projection_hand_computed_scenario():
    ws = _ws()

    record_order_created(ws, "order-1", product_name="Widget", category="general",
                          channel="meta", revenue=100.0)
    record_order_created(ws, "order-2", product_name="Gadget", channel="organic", revenue=50.0)
    record_order_created(ws, "order-3", product_name="Widget", channel="meta", revenue=80.0)
    record_order_canceled(ws, "order-3", reason="fraud_flagged")

    record_payment_captured(ws, "order-1", amount=100.0)
    record_payment_captured(ws, "order-2", amount=50.0)
    record_refund_issued(ws, "order-2", amount=10.0)

    record_supplier_cost_observed(ws, "order-1", product_name="Widget", amount=30.0)
    record_supplier_cost_observed(ws, "order-2", product_name="Gadget", amount=15.0)

    record_ad_spend_observed(ws, channel="meta", amount=40.0)
    record_attribution_claim_observed(ws, "order-1", channel="meta", claimed_revenue=100.0)

    snap = compute_projection(ws)

    assert snap.order_count == 2
    assert snap.canceled_order_count == 1
    assert snap.recognized_revenue == 150.0        # order-3 (canceled) excluded
    assert snap.cash_collected == 140.0             # 100 + 50 - 10 refund
    assert snap.total_supplier_costs == 45.0
    assert snap.total_ad_spend == 40.0
    assert snap.total_refunds == 10.0
    assert snap.gross_profit == 105.0               # 150 - 45
    assert snap.contribution_profit == 55.0         # 105 - 40 ad spend - 10 refund
    assert round(snap.contribution_margin, 4) == round(55.0 / 150.0, 4)
    assert snap.cac_blended == 20.0                 # 40 / 2 orders
    assert snap.cac_by_channel["meta"] == 40.0       # 40 spend / 1 order attributed to meta
    assert snap.cac_by_channel["organic"] == 0.0
    assert snap.profit_per_order == 27.5             # 55 / 2
    assert snap.profit_per_product["Widget"] == 70.0  # 100 revenue - 30 cost
    assert snap.profit_per_product["Gadget"] == 35.0  # 50 revenue - 15 cost
    assert snap.profit_per_channel["meta"] == 60.0    # 100 revenue - 40 spend
    assert snap.profit_per_channel["organic"] == 50.0  # 50 revenue - 0 spend
    assert snap.revenue_by_channel == {"meta": 100.0, "organic": 50.0}
    assert snap.cash_conversion_cycle_days is not None
    assert snap.cash_conversion_cycle_days >= 0.0


def test_compute_projection_workspace_isolation():
    ws_a, ws_b = _ws(), _ws()
    record_order_created(ws_a, "order-a", revenue=100.0)
    record_payment_captured(ws_a, "order-a", amount=100.0)
    record_order_created(ws_b, "order-b", revenue=999.0)

    snap_a = compute_projection(ws_a)
    snap_b = compute_projection(ws_b)

    assert snap_a.recognized_revenue == 100.0
    assert snap_b.recognized_revenue == 999.0
    assert snap_a.order_count == 1
    assert snap_b.order_count == 1


def test_to_dict_rounds_and_serializes():
    ws = _ws()
    record_order_created(ws, "order-1", revenue=99.999)
    record_payment_captured(ws, "order-1", amount=99.999)
    snap = compute_projection(ws)
    d = snap.to_dict()
    assert d["recognized_revenue"] == round(99.999, 2)
    assert isinstance(d["cac_by_channel"], dict)
    assert isinstance(d["profit_per_product"], dict)
