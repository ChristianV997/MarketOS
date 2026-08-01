"""Parity tests: services.unit_economics.from_ledger /
services.ecommerce_operator.contribution_profit.from_ledger against the
existing direct-input entry points, using a synthetic ledger."""
import uuid

from backend.ledger.events import (
    record_ad_spend_observed,
    record_order_created,
    record_payment_captured,
    record_refund_issued,
    record_supplier_cost_observed,
)
from backend.workspaces.client_workspace import ClientWorkspace


def _ws() -> ClientWorkspace:
    return ClientWorkspace(name=f"ledger-svc-{uuid.uuid4().hex[:8]}", workspace_type="internal")


def test_unit_economics_from_ledger_empty_ledger_matches_direct_defaults():
    from services.unit_economics.analyzer import from_ledger, run_unit_economics

    ws = _ws()
    direct, _ = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0, workspace=ws)
    ledger_result, envelope = from_ledger("Widget", workspace=ws, supplier_cost=10.0, retail_price=40.0)

    # No ledger events recorded yet — from_ledger should fall back to the
    # same calculate_margin defaults the direct-input path uses.
    assert ledger_result.base_margin == direct.base_margin
    assert ledger_result.verdict == direct.verdict
    assert envelope.service_name == "unit_economics"


def test_unit_economics_from_ledger_uses_recorded_spend_and_revenue():
    from services.unit_economics.analyzer import from_ledger

    ws = _ws()
    record_order_created(ws.workspace_id, "order-1", product_name="Widget", revenue=40.0, channel="meta")
    record_payment_captured(ws.workspace_id, "order-1", amount=40.0)
    record_ad_spend_observed(ws.workspace_id, channel="meta", amount=200.0)

    result, envelope = from_ledger("Widget", workspace=ws, supplier_cost=10.0, retail_price=40.0)

    from backend.validation.margin_calculator import calculate_margin
    expected = calculate_margin(
        supplier_cost=10.0, retail_price=40.0,
        monthly_ad_spend=200.0, expected_monthly_revenue=40.0,
    )
    assert result.base_margin == expected
    assert envelope.status == "completed"


def test_contribution_profit_from_ledger_empty_ledger_yields_zero_result():
    from backend.experiments.envelope import CommercialRunEnvelope
    from services.ecommerce_operator.contribution_profit import from_ledger

    ws = _ws()
    envelope = CommercialRunEnvelope(
        service_name="ecommerce_operator", workspace_id=ws.workspace_id,
        inputs={"product_name": "Widget"},
    )
    result = from_ledger(envelope)

    assert result.actual_orders == 0
    assert result.contribution_profit == 0.0
    assert result.status == "needs_live_data"
    assert result.has_data is False  # no events recorded yet, not "genuinely zero profit"


def test_contribution_profit_from_ledger_matches_hand_computed_projection():
    from backend.experiments.envelope import CommercialRunEnvelope
    from backend.ledger.projections import compute_projection
    from services.ecommerce_operator.contribution_profit import from_ledger

    ws = _ws()
    record_order_created(ws.workspace_id, "order-1", product_name="Widget", channel="meta", revenue=100.0)
    record_payment_captured(ws.workspace_id, "order-1", amount=100.0)
    record_refund_issued(ws.workspace_id, "order-1", amount=5.0)
    record_supplier_cost_observed(ws.workspace_id, "order-1", product_name="Widget", amount=30.0)
    record_ad_spend_observed(ws.workspace_id, channel="meta", amount=20.0)

    envelope = CommercialRunEnvelope(
        service_name="ecommerce_operator", workspace_id=ws.workspace_id,
        inputs={"product_name": "Widget"},
    )
    result = from_ledger(envelope)
    snapshot = compute_projection(ws.workspace_id)

    assert result.actual_orders == snapshot.order_count == 1
    assert result.actual_spend == snapshot.total_ad_spend == 20.0
    assert result.supplier_costs == snapshot.total_supplier_costs == 30.0
    assert result.refunds == snapshot.total_refunds == 5.0
    # ground_truth_revenue == cash_collected (95.0); reconciliation compares
    # raw campaign_revenue (100.0, from revenue_by_channel) against it.
    assert result.actual_revenue_raw == 100.0
    assert result.actual_revenue_reconciled <= 100.0
    assert result.has_data is True
