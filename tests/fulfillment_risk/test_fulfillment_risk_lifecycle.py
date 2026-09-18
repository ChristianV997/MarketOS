from __future__ import annotations

import pytest

from backend.contracts.events import Event
from backend.economics.kernel import CurrencyMismatchError, EvidenceRef, MarketLane, Money
from backend.events.repository import InMemoryEventRepository
from evaluation.commerce.fulfillment_risk_lifecycle import (
    FULFILLMENT_STATES,
    FixtureFulfillmentAdapter,
    PortObservation,
    build_named_adapter,
    build_named_scenario,
    run_fulfillment_risk_dry_run,
)


def test_named_scenarios_cover_the_required_post_purchase_matrix():
    names = (
        "successful_direct_shipment", "tracking_never_arrives", "shipment_delayed",
        "stock_cancellation_after_payment", "wrong_sku_missing_accessory",
        "damaged_shipment_supplier_reimbursement", "customer_return_merchant_paid",
        "warranty_replacement", "refund_lag_chargeback", "unsupported_missing_route",
        "conflicting_supplier_terms",
    )
    reports = [run_fulfillment_risk_dry_run(build_named_scenario(name), adapter=FixtureFulfillmentAdapter.complete()) for name in names]
    assert all(report.dry_run and not report.live_action_allowed for report in reports)
    assert reports[0].current_state == "contribution_reconciled"
    assert reports[1].current_state == "tracking_pending"
    assert reports[2].current_state == "delayed"
    assert "missing_customer_support_route" in reports[9].blockers
    assert "conflicting_supplier_terms" in reports[10].blockers


def test_named_tracking_fixture_preserves_missing_tracking_evidence():
    report = run_fulfillment_risk_dry_run(
        build_named_scenario("tracking_never_arrives"), adapter=build_named_adapter("tracking_never_arrives")
    )
    assert report.status == "blocked"
    assert "unavailable_tracking" in report.blockers


def test_successful_fixture_shipment_is_simulated_but_not_live_validated():
    report = run_fulfillment_risk_dry_run(
        build_named_scenario("successful_direct_shipment"), adapter=FixtureFulfillmentAdapter.complete()
    )
    assert report.status == "simulated"
    assert report.evidence_state == "assumed"
    assert "supplier_proof_fixture_only" in report.risk_flags
    assert report.live_action_allowed is False
    assert report.provider_calls is False
    assert report.external_mutations is False
    assert report.database_writes is False


def test_tracking_without_an_adapter_is_hold_and_not_a_pass():
    report = run_fulfillment_risk_dry_run(build_named_scenario("tracking_never_arrives"))
    assert report.status == "blocked"
    assert "unavailable_tracking" in report.blockers
    assert "unavailable_supplier_order" in report.blockers
    assert report.next_human_action.startswith("resolve:")


def test_missing_support_and_rma_routes_block_the_order():
    report = run_fulfillment_risk_dry_run(
        build_named_scenario("unsupported_missing_route"), adapter=FixtureFulfillmentAdapter.complete()
    )
    assert report.status == "blocked"
    assert {"missing_customer_support_route", "missing_rma_escalation_route"}.issubset(report.blockers)


def test_catalog_identity_does_not_substitute_for_supplier_proof():
    scenario = build_named_scenario("successful_direct_shipment")
    scenario = scenario.__class__(**{**scenario.__dict__, "supplier_offer": None})
    report = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())
    assert "supplier_proof_missing" in report.blockers
    assert "catalog_is_not_supplier_proof" in report.risk_flags


def test_currency_mismatch_is_rejected_by_the_financial_kernel():
    scenario = build_named_scenario("successful_direct_shipment")
    lane = MarketLane("mx", "CN", "CN", "warehouse", "MX", "CDMX", currency="MXN")
    scenario = scenario.__class__(**{**scenario.__dict__, "lane": lane, "price": Money("10", "USD"), "product_cost": Money("4", "USD")})
    with pytest.raises(CurrencyMismatchError):
        run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())


def test_unavailable_port_evidence_remains_visible_as_hold():
    scenario = build_named_scenario("shipment_delayed")
    adapter = FixtureFulfillmentAdapter({
        "supplier_order": PortObservation("supplier_order", "simulated", "fixture", "fixture:supplier:v1"),
        "supplier_communication": PortObservation("supplier_communication", "unavailable", "unknown", detail_code="no_response"),
        "tracking": PortObservation("tracking", "simulated", "fixture", "fixture:tracking:v1"),
    })
    report = run_fulfillment_risk_dry_run(scenario, adapter=adapter)
    assert report.status == "blocked"
    assert "unavailable_supplier_communication" in report.blockers
    assert "supplier_response_sla_unavailable" in report.sla_risks


def test_event_projection_is_deterministic_and_idempotent():
    scenario = build_named_scenario("successful_direct_shipment")
    first = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())
    second = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())
    assert first.fingerprint == second.fingerprint
    assert [event.replay_hash() for event in first.events] == [event.replay_hash() for event in second.events]
    assert all(event.workspace_id == scenario.workspace_id for event in first.events)
    assert all(event.metadata["live_action_allowed"] is False for event in first.events)
    repository = InMemoryEventRepository()
    first_append = repository.append_many(first.events)
    second_append = repository.append_many(second.events)
    assert all(item.appended for item in first_append)
    assert all(item.idempotent for item in second_append)
    assert len(list(repository.stream(aggregate_id=scenario.order_id))) == len(first.events)


def test_event_envelope_uses_canonical_schema_without_raw_payloads():
    report = run_fulfillment_risk_dry_run(
        build_named_scenario("damaged_shipment_supplier_reimbursement"), adapter=FixtureFulfillmentAdapter.complete()
    )
    assert all(isinstance(event, Event) for event in report.events)
    serialized = report.canonical_json().lower()
    assert len(serialized.encode("utf-8")) <= 64 * 1024
    assert "api_key" not in serialized and "password" not in serialized and "-----begin" not in serialized
    assert "supplier_reimbursement_unknown" in report.reserve_classifications


def test_missing_costs_are_classified_unknown_not_treated_as_free():
    report = run_fulfillment_risk_dry_run(
        build_named_scenario("customer_return_merchant_paid"), adapter=FixtureFulfillmentAdapter.complete()
    )
    assert "unknown_cost:international_shipping" in report.reserve_classifications
    assert "unknown_cost:return_rate" not in report.reserve_classifications
    assert report.economics.international_shipping.source == "assumed_international_shipping"


def test_state_vocabulary_is_closed_and_complete():
    assert len(FULFILLMENT_STATES) == 25
    assert len(set(FULFILLMENT_STATES)) == len(FULFILLMENT_STATES)
    assert FULFILLMENT_STATES[0] == "order_received"
    assert FULFILLMENT_STATES[-1] == "contribution_reconciled"


def test_unsafe_evidence_markers_are_rejected_before_reporting():
    scenario = build_named_scenario("successful_direct_shipment")
    unsafe = EvidenceRef(
        "unsafe", source_type="manual", source_url="https://fixture.invalid/secret/redacted",
        extraction_method="fixture", evidence_state="fixture",
    )
    with pytest.raises(ValueError, match="unsafe"):
        scenario.__class__(**{**scenario.__dict__, "evidence_refs": (unsafe,)})


def test_report_contract_cannot_claim_live_authority():
    report = run_fulfillment_risk_dry_run(
        build_named_scenario("successful_direct_shipment"), adapter=FixtureFulfillmentAdapter.complete()
    )
    with pytest.raises(ValueError, match="offline dry-runs"):
        report.__class__(**{**report.__dict__, "live_action_allowed": True})
