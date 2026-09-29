"""Focused integration and contract tests for fulfillment-risk lifecycle.

Contracts exercised:
- Bundled order across multiple supplier/location candidates.
- Normal reservation, partial allocation, rejection/delay, cancellation, and compensation.
- Deterministic allocations (priority-first, location-id tie-breaking, permutation invariance).
- Missing-vs-zero preservation (0 stock vs missing/rejected evidence vs unverified evidence).
- Strict quantity conservation and anti-over-allocation / anti-over-release guards.
- Compensation LIFO order, idempotency, and no duplicate release after replay.
- Canonical event projection, causation chaining, and repository replay idempotency.
"""
from __future__ import annotations

from decimal import Decimal
import pytest

from backend.economics.kernel import EvidenceRef, MarketLane, Money, UnitEconomicsAssumptions
from backend.events.repository import InMemoryEventRepository
from evaluation.commerce.canonical import (
    CommercialOwnership,
    OwnershipAssignment,
    SupplierOfferIdentity,
)
from evaluation.commerce.fulfillment_risk_lifecycle import (
    FixtureFulfillmentAdapter,
    FulfillmentResponsibilityMap,
    FulfillmentRiskScenario,
    InventoryReservation,
    LocationAllocation,
    LocationStock,
    allocate_multi_location_inventory,
    compensate_reservation,
    reconcile_evidence_refs,
    release_inventory_reservation,
    run_fulfillment_risk_dry_run,
)


def _make_evidence(ev_id: str, state: str = "verified", captured_at: str = "2026-01-01T00:00:00+00:00") -> EvidenceRef:
    return EvidenceRef(
        ev_id,
        source_type="fixture",
        extraction_method="fixture",
        evidence_state=state,
        origin="CN",
        destination="MX",
        captured_at=captured_at,
    )


def _make_scenario(
    name: str = "contract_scenario",
    state_path: tuple[str, ...] | None = None,
    locations: tuple[LocationStock, ...] = (),
    requested_units: int = 1,
) -> FulfillmentRiskScenario:
    evidence = _make_evidence("ev:contract:base", state="fixture")
    lane = MarketLane(
        "cn-mx-contract",
        "CN",
        "CN",
        "wh-contract",
        "MX",
        "CDMX",
        currency="MXN",
        return_destination="fixture-return",
        delivery_promise="3-7 business days",
        evidence_refs=(evidence,),
    )
    ownership = CommercialOwnership(
        *(
            OwnershipAssignment(role, "contract-owner", evidence)
            for role in (
                "merchant_of_record",
                "fulfillment_owner",
                "warranty_owner",
                "return_owner",
                "support_owner",
                "payment_collection_owner",
            )
        ),
        commission_or_margin_method="retail_margin",
    )
    responsibilities = FulfillmentResponsibilityMap(
        ownership=ownership,
        customer_support_route="fixture://support",
        rma_escalation_route="fixture://rma",
        supplier_response_sla="24h",
        delivery_promise="3-7 business days",
        return_destination="fixture-return",
        return_cost_payer="merchant",
        evidence_state="fixture",
        evidence_refs=(evidence,),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("50", "MXN", source="fixture", provenance="fixture", evidence_state="fixture", evidence_ref=evidence),
        return_rate=Decimal("0.05"),
        defect_rate=Decimal("0.02"),
        warranty_rate=Decimal("0.02"),
        support_reserve_rate=Decimal("0.01"),
        chargeback_rate=Decimal("0.01"),
        refund_lag_days=Decimal("14"),
        evidence_refs=(evidence,),
    )
    default_path = (
        "order_received",
        "payment_authorized",
        "payment_captured",
        "supplier_order_drafted",
        "supplier_order_approved",
        "supplier_order_submitted",
        "supplier_accepted",
        "stock_confirmed",
        "tracking_pending",
        "in_transit",
        "delivered",
        "contribution_reconciled",
    )
    offer = SupplierOfferIdentity("contract-supplier", "offer-bundle-01", "SKU-BUNDLE-01", evidence_ref=evidence)
    return FulfillmentRiskScenario(
        scenario_id=f"scn:{name}",
        order_id=f"ord:{name}",
        candidate_id=f"cnd:{name}",
        workspace_id="workspace-contract-test",
        lane=lane,
        price=Money("1200", "MXN", source="fixture", provenance="fixture", evidence_state="fixture", evidence_ref=evidence),
        product_cost=Money("500", "MXN", source="fixture", provenance="fixture", evidence_state="fixture", evidence_ref=evidence),
        assumptions=assumptions,
        responsibilities=responsibilities,
        state_path=state_path or default_path,
        supplier_offer=offer,
        catalog_item_id="cat-item-01",
        flags=(),
        evidence_refs=(evidence,),
        evidence_state="fixture",
        locations=locations,
        requested_units=requested_units,
    )


class TestBundledMultiLocationReservationContract:
    """Exercise bundled orders across multiple supplier/location candidates."""

    def test_bundled_multi_location_candidate_deterministic_allocation_and_priority_ordering(self):
        """Allocation must sort candidates by priority ascending, then location_id ascending."""
        ev1 = _make_evidence("ev:loc:primary-east", state="verified")
        ev2 = _make_evidence("ev:loc:primary-west", state="verified")
        ev3 = _make_evidence("ev:loc:backup-south", state="verified")

        loc_primary_east = LocationStock("loc:sup-1:east", available_units=5, priority=1, warehouse_name="East Hub", evidence_ref=ev1, evidence_state="verified")
        loc_primary_west = LocationStock("loc:sup-1:west", available_units=5, priority=1, warehouse_name="West Hub", evidence_ref=ev2, evidence_state="verified")
        loc_backup_south = LocationStock("loc:sup-2:south", available_units=10, priority=2, warehouse_name="South Hub", evidence_ref=ev3, evidence_state="verified")

        # Order requires 8 units: priority 1 should be exhausted first (5 from east, 3 from west; 0 from south)
        res = allocate_multi_location_inventory(
            order_id="ord:bundle:001",
            sku="SKU-BUNDLE-01",
            requested_units=8,
            locations=(loc_backup_south, loc_primary_west, loc_primary_east),  # shuffled input order
        )

        assert res.status == "reserved"
        assert res.is_fully_allocated is True
        assert res.allocated_units == 8
        assert res.remaining_reserved_units == 8
        assert len(res.allocations) == 2

        # East Hub (priority 1, 'loc:sup-1:east') allocated first (5 units)
        assert res.allocations[0].location_id == "loc:sup-1:east"
        assert res.allocations[0].allocated_units == 5
        assert res.allocations[0].warehouse_name == "East Hub"

        # West Hub (priority 1, 'loc:sup-1:west') allocated second (3 units)
        assert res.allocations[1].location_id == "loc:sup-1:west"
        assert res.allocations[1].allocated_units == 3
        assert res.allocations[1].warehouse_name == "West Hub"

        # Strict quantity conservation
        assert sum(a.allocated_units for a in res.allocations) == res.allocated_units == 8

    def test_bundled_order_partial_allocation_vs_fail_closed_contract(self):
        """Under-stock fails closed by default (allow_partial=False) or allocates available (allow_partial=True)."""
        loc1 = LocationStock("loc:cand-a", available_units=3, priority=1, evidence_state="verified")
        loc2 = LocationStock("loc:cand-b", available_units=4, priority=2, evidence_state="verified")
        # Total available = 7 units, requested = 10 units

        # 1. Fail-closed contract
        res_blocked = allocate_multi_location_inventory(
            order_id="ord:bundle:002",
            sku="SKU-BUNDLE-02",
            requested_units=10,
            locations=(loc1, loc2),
            allow_partial=False,
        )
        assert res_blocked.status == "blocked"
        assert res_blocked.allocated_units == 0
        assert res_blocked.allocations == ()
        assert "insufficient_multi_location_stock" in res_blocked.blockers
        assert res_blocked.is_fully_allocated is False

        # 2. Explicit partial allocation contract
        res_partial = allocate_multi_location_inventory(
            order_id="ord:bundle:002",
            sku="SKU-BUNDLE-02",
            requested_units=10,
            locations=(loc1, loc2),
            allow_partial=True,
        )
        assert res_partial.status == "partially_reserved"
        assert res_partial.allocated_units == 7
        assert res_partial.remaining_reserved_units == 7
        assert len(res_partial.allocations) == 2
        assert res_partial.allocations[0].allocated_units == 3
        assert res_partial.allocations[1].allocated_units == 4
        assert res_partial.is_fully_allocated is False
        assert sum(a.allocated_units for a in res_partial.allocations) == 7

        # 3. No over-allocation invariant: each candidate allocated <= available
        assert res_partial.allocations[0].allocated_units <= loc1.available_units
        assert res_partial.allocations[1].allocated_units <= loc2.available_units

    def test_no_over_allocation_when_requested_less_than_single_candidate(self):
        """When requested units < single candidate stock, only exact requested units are reserved."""
        loc = LocationStock("loc:cand-large", available_units=100, priority=1, evidence_state="verified")
        res = allocate_multi_location_inventory(
            order_id="ord:bundle:003",
            sku="SKU-BUNDLE-03",
            requested_units=4,
            locations=(loc,),
        )
        assert res.status == "reserved"
        assert res.allocated_units == 4
        assert res.allocations[0].allocated_units == 4
        assert res.remaining_reserved_units == 4
        assert res.is_fully_allocated is True


class TestMissingVsZeroPreservationContract:
    """Assert missing-vs-zero preservation across inventory candidates and economics."""

    def test_zero_stock_location_preservation_and_skipping(self):
        """A location with available_units=0 is valid 0 stock, skipped during partial allocation."""
        loc_empty = LocationStock("loc:zero-stock", available_units=0, priority=1, evidence_state="verified")
        loc_active = LocationStock("loc:active-stock", available_units=5, priority=2, evidence_state="verified")

        res = allocate_multi_location_inventory(
            order_id="ord:zero:001",
            sku="SKU-ZERO-01",
            requested_units=3,
            locations=(loc_empty, loc_active),
            allow_partial=True,
        )
        assert res.status == "reserved"
        assert res.allocated_units == 3
        assert len(res.allocations) == 1
        # Only active location is in allocations, zero-stock location is skipped
        assert res.allocations[0].location_id == "loc:active-stock"
        assert res.allocations[0].allocated_units == 3

    def test_all_zero_stock_locations_trigger_zero_stock_available_blocker(self):
        """When all candidate locations have 0 stock, status is blocked with 'zero_stock_available'."""
        loc1 = LocationStock("loc:z1", available_units=0, priority=1, evidence_state="verified")
        loc2 = LocationStock("loc:z2", available_units=0, priority=2, evidence_state="verified")

        res = allocate_multi_location_inventory(
            order_id="ord:zero:002",
            sku="SKU-ZERO-02",
            requested_units=5,
            locations=(loc1, loc2),
            allow_partial=True,
        )
        assert res.status == "blocked"
        assert res.allocated_units == 0
        assert "zero_stock_available" in res.blockers

    def test_missing_evidence_distinguished_from_zero_stock(self):
        """Missing or rejected evidence blocks with specific location blocker rather than generic zero stock."""
        ref_missing = _make_evidence("ev:missing:1", state="missing")
        ref_rejected = _make_evidence("ev:rejected:1", state="rejected")

        loc_missing = LocationStock("loc:miss", available_units=10, evidence_ref=ref_missing, evidence_state="missing")
        loc_rejected = LocationStock("loc:rej", available_units=10, evidence_ref=ref_rejected, evidence_state="rejected")

        res_miss = allocate_multi_location_inventory(
            order_id="ord:ev:001",
            sku="SKU-EV-01",
            requested_units=5,
            locations=(loc_missing,),
        )
        assert res_miss.status == "blocked"
        assert "location_evidence_missing:loc:miss" in res_miss.blockers
        assert "zero_stock_available" not in res_miss.blockers
        assert "insufficient_multi_location_stock" not in res_miss.blockers

        res_rej = allocate_multi_location_inventory(
            order_id="ord:ev:002",
            sku="SKU-EV-02",
            requested_units=5,
            locations=(loc_rejected,),
        )
        assert res_rej.status == "blocked"
        assert "location_evidence_rejected:loc:rej" in res_rej.blockers

    def test_economics_missing_cost_preservation_in_dry_run_report(self):
        """Missing cost inputs in economics are classified as unknown_cost:<item>, not assumed zero."""
        scenario = _make_scenario("missing_cost_test")
        report = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())

        # Assumptions in _make_scenario do not specify payment_processing, international_shipping, etc.
        # These appear in report.reserve_classifications as unknown_cost:*
        unknown_costs = [c for c in report.reserve_classifications if c.startswith("unknown_cost:")]
        assert len(unknown_costs) > 0
        assert "unknown_cost:international_shipping" in unknown_costs
        # Return rate is explicitly specified, so return_rate is not unknown
        assert "unknown_cost:return_rate" not in unknown_costs


class TestRejectionDelayAndCancellationLifecycleContract:
    """Exercise bundled order through rejection, delay, and cancellation paths."""

    def test_unverified_evidence_rejection_when_verification_required(self):
        """When require_verified_evidence=True, observed/assumed evidence fails closed."""
        ev_observed = _make_evidence("ev:obs:1", state="observed")
        loc = LocationStock("loc:obs", available_units=10, evidence_ref=ev_observed, evidence_state="observed")

        res = allocate_multi_location_inventory(
            order_id="ord:rej:001",
            sku="SKU-REJ-01",
            requested_units=5,
            locations=(loc,),
            require_verified_evidence=True,
        )
        assert res.status == "blocked"
        assert "location_evidence_unverified:loc:obs" in res.blockers

    def test_delayed_shipment_lifecycle_preserves_reservation_and_flags_risk(self):
        """A delayed shipment keeps the inventory reservation intact and raises operational review flags."""
        loc1 = LocationStock("loc:del-1", available_units=5, priority=1, evidence_state="verified")
        loc2 = LocationStock("loc:del-2", available_units=5, priority=2, evidence_state="verified")

        delay_path = (
            "order_received",
            "payment_authorized",
            "payment_captured",
            "supplier_order_drafted",
            "supplier_order_approved",
            "supplier_order_submitted",
            "supplier_accepted",
            "stock_confirmed",
            "tracking_pending",
            "delayed",
        )
        scenario = _make_scenario(
            name="delayed_bundle",
            state_path=delay_path,
            locations=(loc1, loc2),
            requested_units=6,
        )

        report = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())

        # In delayed state: reservation is preserved, NOT released
        assert report.current_state == "delayed"
        assert report.reservation is not None
        assert report.reservation.status == "reserved"
        assert report.reservation.allocated_units == 6
        assert report.reservation.remaining_reserved_units == 6
        assert report.compensating_release is None

        # Risk flags & SLA risks
        assert "delivery_promise_at_risk" in report.risk_flags
        assert "inventory_reserved" in report.risk_flags
        assert "inventory_compensated" not in report.risk_flags
        assert "delivery_promise_breach_review" in report.sla_risks
        assert "tracking_or_delivery_sla" in report.sla_risks

        # Next human action
        assert report.next_human_action == "confirm_revised_delivery_promise_and_support_route"

    def test_cancellation_after_stock_confirmed_triggers_automatic_compensating_release(self):
        """When an order cancels after stock confirmation, dry-run automatically creates compensating release."""
        loc_east = LocationStock("loc:c-east", available_units=4, priority=1, evidence_state="verified")
        loc_west = LocationStock("loc:c-west", available_units=6, priority=2, evidence_state="verified")

        # Test cancelled intermediate state directly
        cancel_only_path = (
            "order_received",
            "payment_authorized",
            "payment_captured",
            "cancelled",
        )
        scenario_cancel = _make_scenario(
            name="cancelled_direct",
            state_path=cancel_only_path,
            locations=(loc_east, loc_west),
            requested_units=7,
        )
        report_cancel = run_fulfillment_risk_dry_run(scenario_cancel, adapter=FixtureFulfillmentAdapter.complete())
        assert report_cancel.current_state == "cancelled"
        assert report_cancel.reservation is not None
        assert report_cancel.reservation.status == "released"
        assert "customer_resolution_exposure" in report_cancel.risk_flags
        assert "inventory_compensated" in report_cancel.risk_flags

        # Test subsequent refund_requested state
        cancel_refund_path = (
            "order_received",
            "payment_authorized",
            "payment_captured",
            "cancelled",
            "refund_requested",
        )
        scenario = _make_scenario(
            name="cancelled_bundle",
            state_path=cancel_refund_path,
            locations=(loc_east, loc_west),
            requested_units=7,
        )

        report = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())

        assert report.current_state == "refund_requested"
        assert report.reservation is not None
        assert report.reservation.allocated_units == 7
        assert report.reservation.released_units == 7
        assert report.reservation.remaining_reserved_units == 0
        assert report.reservation.status == "released"

        # Compensating release record
        assert report.compensating_release is not None
        assert report.compensating_release.status == "completed"
        assert report.compensating_release.released_units == 7
        assert report.compensating_release.reason == "lifecycle_compensation:refund_requested"
        assert report.compensating_release.idempotent is False

        # Released allocations conservation
        rel_map = {a.location_id: a.allocated_units for a in report.compensating_release.released_allocations}
        assert rel_map == {"loc:c-east": 4, "loc:c-west": 3}
        assert sum(a.allocated_units for a in report.compensating_release.released_allocations) == 7

        # Risk flags at refund_requested state (reverse logistics exposure attached)
        assert "inventory_compensated" in report.risk_flags
        assert "reverse_logistics_exposure" in report.risk_flags

    def test_failed_delivery_triggers_compensating_release(self):
        """Failed delivery transition triggers compensating release of reserved inventory."""
        loc = LocationStock("loc:fd-1", available_units=10, priority=1, evidence_state="verified")
        fail_path = (
            "order_received",
            "payment_authorized",
            "payment_captured",
            "supplier_order_drafted",
            "supplier_order_approved",
            "supplier_order_submitted",
            "supplier_accepted",
            "stock_confirmed",
            "tracking_pending",
            "in_transit",
            "failed_delivery",
        )
        scenario = _make_scenario(
            name="failed_delivery_bundle",
            state_path=fail_path,
            locations=(loc,),
            requested_units=4,
        )

        report = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete())

        assert report.current_state == "failed_delivery"
        assert report.reservation is not None
        assert report.reservation.status == "released"
        assert report.reservation.remaining_reserved_units == 0
        assert report.compensating_release is not None
        assert report.compensating_release.released_units == 4
        assert report.compensating_release.reason == "lifecycle_compensation:failed_delivery"
        assert "inventory_compensated" in report.risk_flags


class TestCompensationAndReplayIdempotencyContract:
    """Assert LIFO release order, quantity conservation, idempotency, and replay invariants."""

    def test_stepwise_lifo_release_and_strict_quantity_conservation(self):
        """Stepwise releases must follow LIFO order and preserve allocated == remaining + released."""
        alloc1 = LocationAllocation("loc:wh-1", allocated_units=3, warehouse_name="WH 1")
        alloc2 = LocationAllocation("loc:wh-2", allocated_units=4, warehouse_name="WH 2")
        alloc3 = LocationAllocation("loc:wh-3", allocated_units=5, warehouse_name="WH 3")

        res = InventoryReservation(
            reservation_id="res:stepwise:001",
            order_id="ord:stepwise:001",
            sku="SKU-STEP-01",
            requested_units=12,
            allocated_units=12,
            allocations=(alloc1, alloc2, alloc3),
            status="reserved",
        )

        # Step 1: Release 3 units (should come entirely from loc:wh-3, the last allocation)
        res_1, rel_1 = compensate_reservation(res, units_to_release=3, reason="step1_release")
        assert res_1.status == "partially_released"
        assert res_1.released_units == 3
        assert res_1.remaining_reserved_units == 9
        assert rel_1.released_units == 3
        assert len(rel_1.released_allocations) == 1
        assert rel_1.released_allocations[0].location_id == "loc:wh-3"
        assert rel_1.released_allocations[0].allocated_units == 3
        assert res_1.allocated_units == res_1.remaining_reserved_units + res_1.released_units

        # Step 2: Release 4 units (2 remaining from loc:wh-3 + 2 from loc:wh-2)
        res_2, rel_2 = compensate_reservation(res_1, units_to_release=4, reason="step2_release")
        assert res_2.status == "partially_released"
        assert res_2.released_units == 7
        assert res_2.remaining_reserved_units == 5
        assert rel_2.released_units == 4
        rel_2_map = {a.location_id: a.allocated_units for a in rel_2.released_allocations}
        assert rel_2_map == {"loc:wh-2": 2, "loc:wh-3": 2}
        assert res_2.allocated_units == res_2.remaining_reserved_units + res_2.released_units

        # Step 3: Release remaining 5 units (2 from loc:wh-2 + 3 from loc:wh-1)
        res_3, rel_3 = release_inventory_reservation(res_2, reason="final_release")
        assert res_3.status == "released"
        assert res_3.released_units == 12
        assert res_3.remaining_reserved_units == 0
        assert res_3.is_released is True
        assert rel_3.released_units == 5
        rel_3_map = {a.location_id: a.allocated_units for a in rel_3.released_allocations}
        assert rel_3_map == {"loc:wh-1": 3, "loc:wh-2": 2}
        assert res_3.allocated_units == res_3.remaining_reserved_units + res_3.released_units

    def test_oversized_and_invalid_release_requests_rejected_fail_closed(self):
        """Compensating release must reject releases exceeding remaining reserved units or negative amounts."""
        alloc = LocationAllocation("loc:guard", allocated_units=5)
        res = InventoryReservation(
            reservation_id="res:guard:001",
            order_id="ord:guard:001",
            sku="SKU-GUARD-01",
            requested_units=5,
            allocated_units=5,
            allocations=(alloc,),
            status="reserved",
        )

        with pytest.raises(ValueError, match="cannot release 6 units; only 5 remaining reserved"):
            compensate_reservation(res, units_to_release=6)

        with pytest.raises(ValueError, match="units_to_release must be a positive integer"):
            compensate_reservation(res, units_to_release=0)

        with pytest.raises(ValueError, match="units_to_release must be a positive integer"):
            compensate_reservation(res, units_to_release=-1)

    def test_no_duplicate_release_after_replay_and_idempotent_noops(self):
        """Replay compensation on already-released reservation returns idempotent no-op with 0 released units."""
        alloc = LocationAllocation("loc:idemp", allocated_units=4)
        res = InventoryReservation(
            reservation_id="res:idemp:001",
            order_id="ord:idemp:001",
            sku="SKU-IDEMP-01",
            requested_units=4,
            allocated_units=4,
            allocations=(alloc,),
            status="reserved",
        )

        # Initial release
        res_released, rel_initial = compensate_reservation(res)
        assert res_released.status == "released"
        assert rel_initial.status == "completed"
        assert rel_initial.idempotent is False
        assert rel_initial.released_units == 4

        # Replay 1
        res_replay_1, rel_replay_1 = compensate_reservation(res_released)
        assert res_replay_1 == res_released
        assert rel_replay_1.status == "noop"
        assert rel_replay_1.idempotent is True
        assert rel_replay_1.released_units == 0
        assert rel_replay_1.released_allocations == ()

        # Replay 2
        res_replay_2, rel_replay_2 = release_inventory_reservation(res_released)
        assert res_replay_2 == res_released
        assert rel_replay_2.status == "noop"
        assert rel_replay_2.idempotent is True
        assert rel_replay_2.released_units == 0

    def test_projected_events_causation_chaining_and_repository_replay_idempotency(self):
        """Projected events form strict causation chain; appending twice to repository is idempotent."""
        loc = LocationStock("loc:ev-chain", available_units=5, priority=1, evidence_state="verified")
        cancel_path = (
            "order_received",
            "payment_authorized",
            "payment_captured",
            "cancelled",
            "refund_requested",
        )
        scenario = _make_scenario(
            name="causation_replay_test",
            state_path=cancel_path,
            locations=(loc,),
            requested_units=3,
        )

        report = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete(), occurred_at=1000.0)
        events = report.events

        # 1. Event envelope and causation chain
        assert len(events) >= 3
        # Root event (started)
        assert events[0].causation_id is None
        assert events[0].correlation_id == scenario.scenario_id
        assert events[0].event_type == "fulfillment_risk_started"

        # Subsequent events satisfy causation_id == previous.event_id
        for i in range(1, len(events)):
            assert events[i].causation_id == events[i - 1].event_id
            assert events[i].correlation_id == scenario.scenario_id
            assert events[i].workspace_id == scenario.workspace_id
            assert events[i].metadata["live_action_allowed"] is False
            assert events[i].metadata["dry_run"] is True

        # 2. Reservation and compensation event payloads
        assert report.reservation is not None
        assert report.compensating_release is not None

        cancel_events = [e for e in events if e.event_type == "fulfillment_risk_cancelled"]
        assert len(cancel_events) == 1
        assert cancel_events[0].payload["compensating_release_id"] == report.compensating_release.release_id
        assert cancel_events[0].payload["released_units"] == 3
        assert cancel_events[0].metadata["compensating_release_id"] == report.compensating_release.release_id

        completed_events = [e for e in events if e.event_type == "fulfillment_risk_completed"]
        assert len(completed_events) == 1
        assert completed_events[0].payload["reservation_id"] == report.reservation.reservation_id
        assert completed_events[0].payload["compensating_release_id"] == report.compensating_release.release_id

        # 3. InMemoryEventRepository append and replay append
        repo = InMemoryEventRepository()
        first_pass = repo.append_many(events)
        assert all(res.appended for res in first_pass)
        assert all(not res.idempotent for res in first_pass)

        # Replay pass: must be recognized as idempotent and NOT appended again
        second_pass = repo.append_many(events)
        assert all(not res.appended for res in second_pass)
        assert all(res.idempotent for res in second_pass)

        # Stream count equals exactly the original event count (no duplicated release events)
        stream_events = list(repo.stream(aggregate_id=scenario.order_id))
        assert len(stream_events) == len(events)


class TestPermutationInvarianceAndFingerprintContract:
    """Assert permutation invariance of candidates, evidence references, and report fingerprints."""

    def test_candidate_locations_permutation_invariance(self):
        """Input candidate location ordering does not alter reservation allocations or fingerprint."""
        loc1 = LocationStock("loc:perm-1", available_units=5, priority=1, evidence_state="verified")
        loc2 = LocationStock("loc:perm-2", available_units=5, priority=2, evidence_state="verified")
        loc3 = LocationStock("loc:perm-3", available_units=5, priority=3, evidence_state="verified")

        res_fwd = allocate_multi_location_inventory(
            order_id="ord:perm:001",
            sku="SKU-PERM-01",
            requested_units=7,
            locations=(loc1, loc2, loc3),
        )
        res_rev = allocate_multi_location_inventory(
            order_id="ord:perm:001",
            sku="SKU-PERM-01",
            requested_units=7,
            locations=(loc3, loc2, loc1),
        )
        res_shf = allocate_multi_location_inventory(
            order_id="ord:perm:001",
            sku="SKU-PERM-01",
            requested_units=7,
            locations=(loc2, loc3, loc1),
        )

        assert res_fwd.fingerprint == res_rev.fingerprint == res_shf.fingerprint
        assert res_fwd.allocations == res_rev.allocations == res_shf.allocations
        assert res_fwd.allocated_units == res_rev.allocated_units == res_shf.allocated_units == 7

    def test_dry_run_report_fingerprint_and_replay_hash_invariance(self):
        """Two evaluations of the same scenario produce identical report fingerprints and event replay hashes."""
        loc = LocationStock("loc:fprint-1", available_units=10, priority=1, evidence_state="verified")
        scenario = _make_scenario(name="fingerprint_test", locations=(loc,), requested_units=4)

        report_1 = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete(), occurred_at=500.0)
        report_2 = run_fulfillment_risk_dry_run(scenario, adapter=FixtureFulfillmentAdapter.complete(), occurred_at=500.0)

        assert report_1.fingerprint == report_2.fingerprint
        assert report_1.canonical_json() == report_2.canonical_json()
        assert [e.replay_hash() for e in report_1.events] == [e.replay_hash() for e in report_2.events]

    def test_evidence_reconciliation_dedup_and_canonical_sorting(self):
        """reconcile_evidence_refs deduplicates by evidence_id, takes latest captured_at, and sorts canonically."""
        ev_early = _make_evidence("ev:shared:1", state="observed", captured_at="2026-01-01T00:00:00+00:00")
        ev_late = _make_evidence("ev:shared:1", state="verified", captured_at="2026-01-02T12:00:00+00:00")
        ev_alpha = _make_evidence("ev:alpha:1", state="verified")
        ev_omega = _make_evidence("ev:omega:1", state="verified")

        reconciled_1 = reconcile_evidence_refs([ev_omega, ev_early, ev_alpha, ev_late])
        reconciled_2 = reconcile_evidence_refs([ev_late, ev_alpha, ev_early, ev_omega])

        assert len(reconciled_1) == 3
        assert [r.evidence_id for r in reconciled_1] == ["ev:alpha:1", "ev:omega:1", "ev:shared:1"]
        # Latest captured_at ('2026-01-02T12:00:00+00:00' with state 'verified') won
        shared_ref = next(r for r in reconciled_1 if r.evidence_id == "ev:shared:1")
        assert shared_ref.captured_at == "2026-01-02T12:00:00+00:00"
        assert shared_ref.evidence_state == "verified"

        # Permutation invariant
        assert reconciled_1 == reconciled_2
