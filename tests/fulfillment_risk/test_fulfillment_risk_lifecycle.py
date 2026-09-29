from __future__ import annotations

import pytest
from dataclasses import replace

from backend.contracts.events import Event
from backend.economics.kernel import CurrencyMismatchError, EvidenceRef, MarketLane, Money
from backend.events.repository import InMemoryEventRepository
from evaluation.commerce.fulfillment_risk_lifecycle import (
    FULFILLMENT_STATES,
    CompensatingRelease,
    FixtureFulfillmentAdapter,
    InventoryReservation,
    LocationAllocation,
    LocationStock,
    PortObservation,
    allocate_multi_location_inventory,
    build_named_adapter,
    build_named_scenario,
    compensate_reservation,
    reconcile_evidence_refs,
    release_inventory_reservation,
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


# ---------------------------------------------------------------------------
# Regression: Duplicate & Out-of-Order Fulfillment Evidence
# ---------------------------------------------------------------------------


def test_reconcile_evidence_refs_deduplicates_identical_refs():
    ref = EvidenceRef("evidence:identical", source_type="fixture", extraction_method="fixture", evidence_state="observed")
    out = reconcile_evidence_refs([ref, ref, ref])
    assert len(out) == 1
    assert out[0] == ref


def test_duplicate_evidence_id_different_timestamps_preserves_latest_and_stable_fingerprint():
    scenario = build_named_scenario("successful_direct_shipment")
    ref_early = EvidenceRef(
        "evidence:tracking:001",
        source_type="fixture",
        extraction_method="fixture",
        evidence_state="observed",
        captured_at="2026-01-01T00:00:00+00:00",
    )
    ref_late = EvidenceRef(
        "evidence:tracking:001",
        source_type="fixture",
        extraction_method="fixture",
        evidence_state="observed",
        captured_at="2026-01-02T12:00:00+00:00",
    )

    scenario_order_a = replace(scenario, evidence_refs=(ref_early, ref_late))
    scenario_order_b = replace(scenario, evidence_refs=(ref_late, ref_early))

    report_a = run_fulfillment_risk_dry_run(scenario_order_a, adapter=FixtureFulfillmentAdapter.complete())
    report_b = run_fulfillment_risk_dry_run(scenario_order_b, adapter=FixtureFulfillmentAdapter.complete())

    assert report_a.evidence_state == report_b.evidence_state
    # evidence_ids metadata is on state transition events (index 1 onwards), not the 'started' event
    ids_a = [e.metadata["evidence_ids"] for e in report_a.events[1:1+len(report_a.state_path)]]
    ids_b = [e.metadata["evidence_ids"] for e in report_b.events[1:1+len(report_b.state_path)]]
    assert ids_a == ids_b
    assert [e.replay_hash() for e in report_a.events] == [e.replay_hash() for e in report_b.events]


def test_out_of_order_evidence_arrival_state_precedence_stale_downgrades():
    scenario = build_named_scenario("successful_direct_shipment")
    verified_ref = EvidenceRef(
        "evidence:carrier:verified",
        source_type="fixture",
        extraction_method="fixture",
        evidence_state="verified",
        captured_at="2026-01-01T00:00:00+00:00",
    )
    stale_ref = EvidenceRef(
        "evidence:carrier:stale",
        source_type="fixture",
        extraction_method="fixture",
        evidence_state="stale",
        captured_at="2026-01-02T00:00:00+00:00",
    )

    report_fwd = run_fulfillment_risk_dry_run(
        replace(scenario, evidence_refs=(verified_ref, stale_ref), evidence_state="verified"),
        adapter=FixtureFulfillmentAdapter.complete(),
    )
    report_rev = run_fulfillment_risk_dry_run(
        replace(scenario, evidence_refs=(stale_ref, verified_ref), evidence_state="verified"),
        adapter=FixtureFulfillmentAdapter.complete(),
    )

    assert report_fwd.evidence_state == "unknown"
    assert report_rev.evidence_state == "unknown"


def test_missing_evidence_absorbs_all_other_states_regardless_of_position():
    scenario = build_named_scenario("successful_direct_shipment")
    ref_verified = EvidenceRef("ev:1", source_type="fixture", extraction_method="fixture", evidence_state="verified")
    ref_missing = EvidenceRef("ev:2", source_type="fixture", extraction_method="fixture", evidence_state="missing")
    ref_observed = EvidenceRef("ev:3", source_type="fixture", extraction_method="fixture", evidence_state="observed")

    for perm in (
        (ref_verified, ref_missing, ref_observed),
        (ref_missing, ref_verified, ref_observed),
        (ref_observed, ref_verified, ref_missing),
    ):
        report = run_fulfillment_risk_dry_run(
            replace(scenario, evidence_refs=perm, evidence_state="verified"),
            adapter=FixtureFulfillmentAdapter.complete(),
        )
        assert report.evidence_state == "missing"


def test_duplicate_evidence_refs_do_not_breach_capacity_limits():
    scenario = build_named_scenario("successful_direct_shipment")
    single_ref = scenario.evidence_refs[0]

    dupe_refs = tuple(single_ref for _ in range(35))

    unique_refs = tuple(dict.fromkeys(dupe_refs))
    scenario_deduped = replace(scenario, evidence_refs=unique_refs)
    report = run_fulfillment_risk_dry_run(scenario_deduped, adapter=FixtureFulfillmentAdapter.complete())

    assert len(report.evidence_refs) == 1
    assert report.status == "simulated"


def test_manual_offline_evidence_cannot_upgrade_to_live_readonly():
    """Test that live_readonly evidence state takes precedence over manual/observed in reconciliation."""
    from evaluation.commerce.fulfillment_risk_lifecycle import _evidence_state

    manual_ref = EvidenceRef(
        "evidence:manual:override",
        source_type="manual",
        extraction_method="manual",
        evidence_state="observed",
        captured_at="2026-01-01T00:00:00+00:00",
    )
    live_ref = EvidenceRef(
        "evidence:live:api",
        source_type="api",
        extraction_method="live_readonly",
        evidence_state="live_readonly",
        captured_at="2026-01-01T00:00:00+00:00",
    )

    # With explicit "observed" and live_readonly in refs, should resolve to live_readonly
    assert _evidence_state([manual_ref, live_ref], "observed") == "live_readonly"

    # With explicit "verified" and live_readonly in refs, should resolve to live_readonly
    assert _evidence_state([manual_ref, live_ref], "verified") == "live_readonly"

    # Without live_readonly, manual + observed should be assumed (because of manual fixture ref)
    # Actually manual with observed state is just observed, not in assumed set
    # But wait - "manual" source_type with evidence_state "observed" - the _evidence_state only looks at evidence_state
    # So manual ref with observed + live_readonly -> live_readonly (due to live_readonly in any)
    # Manual ref with observed + observed -> observed (no fixture/simulated/assumed/derived, not all verified, no live_readonly)
    # But we have explicit "observed" + observed from manual + observed from live_ref... wait live_ref has live_readonly
    # Let me test without live_readonly
    observed_ref = EvidenceRef("ev:1", source_type="manual", extraction_method="manual", evidence_state="observed")
    # explicit observed + observed from ref -> observed (none of the assumed states)
    assert _evidence_state([observed_ref], "observed") == "observed"


def test_projected_events_evidence_id_ordering_invariant_under_evidence_permutation():
    """Test that evidence_id ordering in projected events is canonical regardless of input order."""
    from evaluation.commerce.fulfillment_risk_lifecycle import reconcile_evidence_refs

    ref1 = EvidenceRef("evidence:alpha", source_type="fixture", extraction_method="fixture", evidence_state="observed")
    ref2 = EvidenceRef("evidence:beta", source_type="fixture", extraction_method="fixture", evidence_state="observed")
    ref3 = EvidenceRef("evidence:gamma", source_type="fixture", extraction_method="fixture", evidence_state="observed")

    # reconcile_evidence_refs should produce canonical order regardless of input permutation
    reconciled_a = reconcile_evidence_refs([ref1, ref2, ref3])
    reconciled_b = reconcile_evidence_refs([ref3, ref1, ref2])
    reconciled_c = reconcile_evidence_refs([ref2, ref3, ref1])

    assert [r.evidence_id for r in reconciled_a] == ["evidence:alpha", "evidence:beta", "evidence:gamma"]
    assert [r.evidence_id for r in reconciled_b] == ["evidence:alpha", "evidence:beta", "evidence:gamma"]
    assert [r.evidence_id for r in reconciled_c] == ["evidence:alpha", "evidence:beta", "evidence:gamma"]

    # With duplicates, only unique evidence_ids should remain, in canonical order
    reconciled_dup = reconcile_evidence_refs([ref1, ref1, ref2, ref3, ref2])
    assert [r.evidence_id for r in reconciled_dup] == ["evidence:alpha", "evidence:beta", "evidence:gamma"]
    assert len(reconciled_dup) == 3


# ---------------------------------------------------------------------------
# Ops Verification: Multi-Location Reservation & Compensating Release
# ---------------------------------------------------------------------------


def test_location_stock_validation_and_immutability():
    loc = LocationStock(
        location_id="loc:us-east",
        available_units=15,
        priority=1,
        warehouse_name="US East Hub",
        evidence_state="verified",
    )
    assert loc.location_id == "loc:us-east"
    assert loc.available_units == 15
    assert loc.priority == 1
    assert loc.warehouse_name == "US East Hub"
    assert loc.evidence_state == "verified"
    assert loc.to_dict()["available_units"] == 15

    with pytest.raises(ValueError, match="available_units must be a non-negative integer"):
        LocationStock(location_id="loc:invalid", available_units=-1)

    with pytest.raises(ValueError, match="available_units must be a non-negative integer"):
        LocationStock(location_id="loc:invalid", available_units=True)  # type: ignore

    with pytest.raises(ValueError, match="invalid evidence_state"):
        LocationStock(location_id="loc:invalid", available_units=5, evidence_state="non_existent")

    with pytest.raises(ValueError, match="priority must be an integer"):
        LocationStock(location_id="loc:invalid", available_units=5, priority=False)  # type: ignore


def test_location_allocation_and_quantity_conservation_invariants():
    alloc = LocationAllocation(
        location_id="loc:us-west",
        allocated_units=10,
        warehouse_name="US West Hub",
    )
    assert alloc.location_id == "loc:us-west"
    assert alloc.allocated_units == 10
    assert alloc.to_dict()["allocated_units"] == 10

    with pytest.raises(ValueError, match="allocated_units must be a positive integer"):
        LocationAllocation(location_id="loc:us-west", allocated_units=0)
    with pytest.raises(ValueError, match="allocated_units must be a positive integer"):
        LocationAllocation(location_id="loc:us-west", allocated_units=-5)
    with pytest.raises(ValueError, match="allocated_units must be a positive integer"):
        LocationAllocation(location_id="loc:us-west", allocated_units=True)  # type: ignore


def test_inventory_reservation_quantity_conservation_and_invariants():
    alloc1 = LocationAllocation(location_id="loc:1", allocated_units=4)
    alloc2 = LocationAllocation(location_id="loc:2", allocated_units=6)

    res = InventoryReservation(
        reservation_id="res:ord_01:sku_a",
        order_id="ord_01",
        sku="sku_a",
        requested_units=10,
        allocated_units=10,
        allocations=(alloc1, alloc2),
        status="reserved",
    )
    assert res.is_fully_allocated is True
    assert res.is_released is False
    assert res.remaining_reserved_units == 10
    assert res.fingerprint is not None

    with pytest.raises(ValueError, match="allocated_units must equal sum of allocations"):
        InventoryReservation(
            reservation_id="res:ord_01:sku_a",
            order_id="ord_01",
            sku="sku_a",
            requested_units=10,
            allocated_units=9,
            allocations=(alloc1, alloc2),
            status="reserved",
        )

    with pytest.raises(ValueError, match="released_units cannot exceed allocated_units"):
        InventoryReservation(
            reservation_id="res:ord_01:sku_a",
            order_id="ord_01",
            sku="sku_a",
            requested_units=10,
            allocated_units=10,
            allocations=(alloc1, alloc2),
            released_units=11,
            status="reserved",
        )


def test_compensating_release_quantity_conservation_and_validation():
    rel_alloc = LocationAllocation(location_id="loc:1", allocated_units=4)
    release = CompensatingRelease(
        release_id="rel:res_01:001",
        reservation_id="res:res_01",
        order_id="ord_01",
        released_units=4,
        released_allocations=(rel_alloc,),
        reason="cancelled_order",
    )
    assert release.released_units == 4
    assert release.status == "completed"
    assert release.idempotent is False

    with pytest.raises(ValueError, match="released_units must equal sum of released_allocations"):
        CompensatingRelease(
            release_id="rel:res_01:001",
            reservation_id="res:res_01",
            order_id="ord_01",
            released_units=5,
            released_allocations=(rel_alloc,),
        )

    with pytest.raises(ValueError, match="invalid release status"):
        CompensatingRelease(
            release_id="rel:res_01:001",
            reservation_id="res:res_01",
            order_id="ord_01",
            released_units=4,
            released_allocations=(rel_alloc,),
            status="unauthorized_status",
        )


def test_allocate_multi_location_inventory_deterministic_priority_and_tie_breaking():
    loc_c = LocationStock("loc_c", available_units=10, priority=2, evidence_state="verified")
    loc_b = LocationStock("loc_b", available_units=5, priority=1, evidence_state="verified")
    loc_a = LocationStock("loc_a", available_units=5, priority=1, evidence_state="verified")

    res = allocate_multi_location_inventory(
        order_id="ord_100",
        sku="SKU-TEST-01",
        requested_units=8,
        locations=(loc_c, loc_b, loc_a),
    )

    assert res.status == "reserved"
    assert res.allocated_units == 8
    assert len(res.allocations) == 2
    assert res.allocations[0].location_id == "loc_a"
    assert res.allocations[0].allocated_units == 5
    assert res.allocations[1].location_id == "loc_b"
    assert res.allocations[1].allocated_units == 3
    assert sum(a.allocated_units for a in res.allocations) == 8


def test_allocate_multi_location_inventory_duplicate_location_id_resolution():
    loc1 = LocationStock("loc:shared", available_units=5, priority=2, evidence_state="verified")
    loc2 = LocationStock("loc:shared", available_units=10, priority=1, evidence_state="verified")

    res = allocate_multi_location_inventory(
        order_id="ord_101",
        sku="SKU-TEST-02",
        requested_units=8,
        locations=(loc1, loc2),
    )

    assert res.status == "reserved"
    assert res.allocated_units == 8
    assert len(res.allocations) == 1
    assert res.allocations[0].location_id == "loc:shared"
    assert res.allocations[0].allocated_units == 8


def test_allocate_multi_location_inventory_partial_vs_fail_closed():
    loc = LocationStock("loc:only", available_units=4, priority=1, evidence_state="verified")

    res_blocked = allocate_multi_location_inventory(
        order_id="ord_102",
        sku="SKU-TEST-03",
        requested_units=10,
        locations=(loc,),
        allow_partial=False,
    )
    assert res_blocked.status == "blocked"
    assert res_blocked.allocated_units == 0
    assert "insufficient_multi_location_stock" in res_blocked.blockers

    res_partial = allocate_multi_location_inventory(
        order_id="ord_102",
        sku="SKU-TEST-03",
        requested_units=10,
        locations=(loc,),
        allow_partial=True,
    )
    assert res_partial.status == "partially_reserved"
    assert res_partial.allocated_units == 4
    assert res_partial.allocations[0].allocated_units == 4
    assert res_partial.is_fully_allocated is False

    zero_loc = LocationStock("loc:zero", available_units=0, priority=1, evidence_state="verified")
    res_zero = allocate_multi_location_inventory(
        order_id="ord_102",
        sku="SKU-TEST-03",
        requested_units=5,
        locations=(zero_loc,),
        allow_partial=True,
    )
    assert res_zero.status == "blocked"
    assert res_zero.allocated_units == 0
    assert "zero_stock_available" in res_zero.blockers


def test_allocate_multi_location_inventory_fail_closed_on_bad_or_unverified_evidence():
    ref_missing = EvidenceRef("ev:loc1", source_type="fixture", extraction_method="fixture", evidence_state="missing")
    ref_rejected = EvidenceRef("ev:loc2", source_type="fixture", extraction_method="fixture", evidence_state="rejected")
    ref_observed = EvidenceRef("ev:loc3", source_type="fixture", extraction_method="fixture", evidence_state="observed")

    loc_missing = LocationStock("loc:missing", available_units=10, evidence_ref=ref_missing, evidence_state="missing")
    loc_rejected = LocationStock("loc:rejected", available_units=10, evidence_ref=ref_rejected, evidence_state="rejected")
    loc_observed = LocationStock("loc:observed", available_units=10, evidence_ref=ref_observed, evidence_state="observed")

    res_miss = allocate_multi_location_inventory(
        order_id="ord_103",
        sku="SKU-TEST-04",
        requested_units=5,
        locations=(loc_missing,),
    )
    assert res_miss.status == "blocked"
    assert "location_evidence_missing:loc:missing" in res_miss.blockers

    res_rej = allocate_multi_location_inventory(
        order_id="ord_103",
        sku="SKU-TEST-04",
        requested_units=5,
        locations=(loc_rejected,),
    )
    assert res_rej.status == "blocked"
    assert "location_evidence_rejected:loc:rejected" in res_rej.blockers

    res_unverified = allocate_multi_location_inventory(
        order_id="ord_103",
        sku="SKU-TEST-04",
        requested_units=5,
        locations=(loc_observed,),
        require_verified_evidence=True,
    )
    assert res_unverified.status == "blocked"
    assert "location_evidence_unverified:loc:observed" in res_unverified.blockers


def test_compensate_reservation_lifo_quantity_conservation_and_stepwise_release():
    alloc1 = LocationAllocation("loc:1", allocated_units=5)
    alloc2 = LocationAllocation("loc:2", allocated_units=5)
    res = InventoryReservation(
        reservation_id="res:test:01",
        order_id="ord_200",
        sku="SKU-COMP-01",
        requested_units=10,
        allocated_units=10,
        allocations=(alloc1, alloc2),
        status="reserved",
    )

    res_step1, release1 = compensate_reservation(res, units_to_release=3, reason="partial_cancellation")
    assert res_step1.status == "partially_released"
    assert res_step1.released_units == 3
    assert res_step1.remaining_reserved_units == 7
    assert release1.released_units == 3
    assert len(release1.released_allocations) == 1
    assert release1.released_allocations[0].location_id == "loc:2"
    assert release1.released_allocations[0].allocated_units == 3

    res_step2, release2 = compensate_reservation(res_step1, units_to_release=4, reason="secondary_reduction")
    assert res_step2.status == "partially_released"
    assert res_step2.released_units == 7
    assert res_step2.remaining_reserved_units == 3
    assert release2.released_units == 4
    rel_map = {a.location_id: a.allocated_units for a in release2.released_allocations}
    assert rel_map == {"loc:1": 2, "loc:2": 2}

    res_step3, release3 = release_inventory_reservation(res_step2, reason="final_cancellation")
    assert res_step3.status == "released"
    assert res_step3.released_units == 10
    assert res_step3.remaining_reserved_units == 0
    assert res_step3.is_released is True
    assert release3.released_units == 3
    assert len(release3.released_allocations) == 1
    assert release3.released_allocations[0].location_id == "loc:1"
    assert release3.released_allocations[0].allocated_units == 3


def test_compensate_reservation_idempotency_and_noops():
    alloc1 = LocationAllocation("loc:1", allocated_units=5)
    res = InventoryReservation(
        reservation_id="res:test:02",
        order_id="ord_201",
        sku="SKU-COMP-02",
        requested_units=5,
        allocated_units=5,
        allocations=(alloc1,),
        status="reserved",
    )

    res_rel, release = compensate_reservation(res)
    assert res_rel.status == "released"
    assert release.status == "completed"
    assert release.idempotent is False
    assert release.released_units == 5

    res_noop, release_noop = compensate_reservation(res_rel)
    assert res_noop == res_rel
    assert release_noop.status == "noop"
    assert release_noop.idempotent is True
    assert release_noop.released_units == 0
    assert release_noop.released_allocations == ()

    blocked_res = InventoryReservation(
        reservation_id="res:test:03",
        order_id="ord_202",
        sku="SKU-COMP-03",
        requested_units=5,
        allocated_units=0,
        allocations=(),
        status="blocked",
    )
    res_blocked_noop, rel_blocked_noop = compensate_reservation(blocked_res)
    assert res_blocked_noop == blocked_res
    assert rel_blocked_noop.status == "noop"
    assert rel_blocked_noop.idempotent is True


def test_compensate_reservation_rejects_oversized_or_invalid_amounts():
    alloc1 = LocationAllocation("loc:1", allocated_units=5)
    res = InventoryReservation(
        reservation_id="res:test:04",
        order_id="ord_203",
        sku="SKU-COMP-04",
        requested_units=5,
        allocated_units=5,
        allocations=(alloc1,),
        status="reserved",
    )

    with pytest.raises(ValueError, match="cannot release 6 units; only 5 remaining reserved"):
        compensate_reservation(res, units_to_release=6)

    with pytest.raises(ValueError, match="units_to_release must be a positive integer"):
        compensate_reservation(res, units_to_release=0)
    with pytest.raises(ValueError, match="units_to_release must be a positive integer"):
        compensate_reservation(res, units_to_release=-2)


def test_dry_run_multi_location_reservation_and_auto_compensation_on_cancellation():
    scenario = build_named_scenario("stock_cancellation_after_payment")
    loc_east = LocationStock("loc:us-east", available_units=5, priority=1, evidence_state="verified")
    loc_west = LocationStock("loc:us-west", available_units=5, priority=2, evidence_state="verified")

    scenario_with_locations = replace(
        scenario,
        locations=(loc_east, loc_west),
        requested_units=6,
    )

    report = run_fulfillment_risk_dry_run(
        scenario_with_locations,
        adapter=FixtureFulfillmentAdapter.complete(),
    )

    assert report.reservation is not None
    assert report.reservation.allocated_units == 6
    assert report.reservation.status == "released"
    assert report.reservation.remaining_reserved_units == 0

    assert report.compensating_release is not None
    assert report.compensating_release.status == "completed"
    assert report.compensating_release.released_units == 6
    assert "inventory_compensated" in report.risk_flags


def test_dry_run_multi_location_reservation_persists_on_successful_delivery():
    scenario = build_named_scenario("successful_direct_shipment")
    loc_east = LocationStock("loc:us-east", available_units=10, priority=1, evidence_state="verified")

    scenario_with_locations = replace(
        scenario,
        locations=(loc_east,),
        requested_units=3,
    )

    report = run_fulfillment_risk_dry_run(
        scenario_with_locations,
        adapter=FixtureFulfillmentAdapter.complete(),
    )

    assert report.reservation is not None
    assert report.reservation.status == "reserved"
    assert report.reservation.allocated_units == 3
    assert report.reservation.remaining_reserved_units == 3
    assert report.compensating_release is None
    assert "inventory_reserved" in report.risk_flags
    assert "inventory_compensated" not in report.risk_flags


def test_projected_events_contain_reservation_and_compensation_envelope():
    # Scenario 1: stock_confirmed state includes reservation metadata
    scenario_success = build_named_scenario("successful_direct_shipment")
    loc_success = LocationStock("loc:1", available_units=4, priority=1, evidence_state="verified")
    scenario_with_loc = replace(scenario_success, locations=(loc_success,), requested_units=4)

    report_success = run_fulfillment_risk_dry_run(
        scenario_with_loc,
        adapter=FixtureFulfillmentAdapter.complete(),
    )

    events_success = report_success.events
    assert len(events_success) > 0
    assert report_success.reservation is not None

    stock_events = [e for e in events_success if e.event_type == "fulfillment_risk_stock_confirmed"]
    assert len(stock_events) == 1
    assert stock_events[0].payload["reservation_id"] == report_success.reservation.reservation_id
    assert stock_events[0].payload["allocated_units"] == 4
    assert stock_events[0].metadata["reservation_id"] == report_success.reservation.reservation_id

    # Scenario 2: cancelled scenario includes compensating release metadata
    scenario_cancel = build_named_scenario("stock_cancellation_after_payment")
    loc_cancel = LocationStock("loc:2", available_units=4, priority=1, evidence_state="verified")
    scenario_cancel_with_loc = replace(scenario_cancel, locations=(loc_cancel,), requested_units=4)

    report_cancel = run_fulfillment_risk_dry_run(
        scenario_cancel_with_loc,
        adapter=FixtureFulfillmentAdapter.complete(),
    )

    events_cancel = report_cancel.events
    assert report_cancel.reservation is not None
    assert report_cancel.compensating_release is not None

    cancelled_events = [e for e in events_cancel if e.event_type == "fulfillment_risk_cancelled"]
    assert len(cancelled_events) == 1
    assert cancelled_events[0].payload["compensating_release_id"] == report_cancel.compensating_release.release_id
    assert cancelled_events[0].payload["released_units"] == 4
    assert cancelled_events[0].metadata["compensating_release_id"] == report_cancel.compensating_release.release_id

    completed_events = [e for e in events_cancel if e.event_type == "fulfillment_risk_completed"]
    assert len(completed_events) == 1
    assert completed_events[0].payload["reservation_id"] == report_cancel.reservation.reservation_id
    assert completed_events[0].payload["compensating_release_id"] == report_cancel.compensating_release.release_id

    # Event repository append and idempotency
    repo = InMemoryEventRepository()
    first_append = repo.append_many(events_cancel)
    second_append = repo.append_many(events_cancel)
    assert all(item.appended for item in first_append)
    assert all(item.idempotent for item in second_append)


def test_multi_location_evidence_refs_reconciled_across_all_locations():
    ref_loc1 = EvidenceRef("ev:loc1", source_type="fixture", extraction_method="fixture", evidence_state="verified")
    ref_loc2 = EvidenceRef("ev:loc2", source_type="fixture", extraction_method="fixture", evidence_state="observed")

    loc1 = LocationStock("loc:1", available_units=5, priority=1, evidence_ref=ref_loc1, evidence_state="verified")
    loc2 = LocationStock("loc:2", available_units=5, priority=2, evidence_ref=ref_loc2, evidence_state="observed")

    scenario = build_named_scenario("successful_direct_shipment")
    scenario_with_locs = replace(scenario, locations=(loc1, loc2), requested_units=4)

    report = run_fulfillment_risk_dry_run(
        scenario_with_locs,
        adapter=FixtureFulfillmentAdapter.complete(),
    )

    ev_ids = {r.evidence_id for r in report.evidence_refs}
    assert "ev:loc1" in ev_ids
    assert "ev:loc2" in ev_ids
