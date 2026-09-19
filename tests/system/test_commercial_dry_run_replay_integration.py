"""Cross-system integration harness for the canonical commerce dry-run lifecycle.

Proves MarketOS behaves as an *integrated* dry-run system, not a collection
of isolated modules: it drives the real public builders from
``evaluation.commerce`` (PR #250's dry-run lifecycle/scenarios and the
financial-evidence kernel it consumes from PR #248) through the real
canonical event envelope (``backend.contracts.events.Event`` +
``backend.events.replay_certification``), the real TrustOS client-workspace
leakage checker, and the real CompanyOS resource execution governor.

This module intentionally reuses every existing authority rather than
building a parallel one:
  - event system: ``backend.contracts.events.Event`` + ``backend.events.replay_certification``
  - money/economics: ``backend.economics.kernel`` (via ``evaluation.commerce.dry_run_lifecycle``)
  - workspace/export boundary: ``evaluation.trustos.client_workspace_isolation``
  - live-action gating: ``evaluation.companyos.resource_execution_governor``
  - approval boundary: ``evaluation.companyos.approval_ledger``

The artifact-store checks below use the current workspace-bound API. The
path-traversal regression is asserted here as an integration contract after
PR #211's security repair; the implementation remains owned by the artifact
store module.
"""
from __future__ import annotations

import json
from decimal import Decimal

import pytest

from backend.contracts.events import Event
from backend.economics.kernel import Money
from backend.events.replay_certification import replay_summary
from backend.workspaces.artifact_store import ArtifactStore
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from evaluation.commerce.dry_run_events import lifecycle_events
from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
from evaluation.commerce.dry_run_scenarios import (
    SCENARIO_BUILDERS,
    commodity_electronics_rejected_candidate,
    high_ticket_deferred_candidate,
    hydroponics_positive_candidate,
    smart_pet_support_burden_candidate,
    solar_4g_security_blocked_candidate,
)
from evaluation.companyos.resource_execution_governor import ExecutionDecisionRequest, evaluate_execution_request
from evaluation.companyos.service_engagement import build_service_engagement
from evaluation.readiness import evaluate_product
from evaluation.contracts import DataQuality, ProductCandidate, SupplierOffer
from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
from scripts.run_commercial_replay_integration import (
    EVIDENCE_CLASS_VOCABULARY,
    run_consolidated_scenario,
    run_scenarios,
)

_EXPECTED_STAGES = {
    "hydroponics_positive_candidate": "scale_candidate",
    "smart_pet_support_burden_candidate": "supplier_validated",
    "solar_4g_security_blocked_candidate": "economics_screened",
    "commodity_electronics_rejected_candidate": "supplier_terms_pending",
    "high_ticket_deferred_candidate": "supplier_validated",
}


def _events_for(builder, workspace_id: str) -> tuple[list[Event], "DryRunLifecycleReport"]:  # noqa: F821 - forward ref for readability
    report = run_dry_run_lifecycle(builder())
    return lifecycle_events(report, workspace_id=workspace_id), report


# ---------------------------------------------------------------------------
# A. Integration scenario harness (real builders, real event projection)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder", SCENARIO_BUILDERS, ids=[b.__name__ for b in SCENARIO_BUILDERS])
def test_scenario_runs_through_real_builders_and_emits_a_clean_event_trail(builder):
    events, report = _events_for(builder, workspace_id=f"ws-{builder.__name__}")
    summary = replay_summary(events)

    assert report.achievable_stage == _EXPECTED_STAGES[report.scenario_id]
    assert summary["sequence_issues"] == []
    assert summary["live_authority_violations"] == []
    assert summary["event_count"] == len(events) == 17  # 1 start + 15 lifecycle steps + 1 completed
    assert all(workspace == f"ws-{builder.__name__}" for workspace in summary["workspace_ids"])


def test_service_client_with_insufficient_data_is_data_inadequate_not_a_guess():
    engagement = build_service_engagement(
        "eng-insufficient", "Managed Acquisition and CRO", "Thin Data Client",
        service_fee=Money("1500", "USD"), inputs={},
    )
    result = engagement.to_dict()
    assert result["status"] == "data_inadequate"
    assert result["economics"] is None
    assert result["reasons"], "must record exactly what is missing, never guess"


def test_service_client_with_adequate_data_computes_real_fee_value_analysis():
    engagement = build_service_engagement(
        "eng-adequate", "Managed Acquisition and CRO", "Adequate Data Client",
        service_fee=Money("1500", "USD"),
        inputs={
            "ad_spend": Money("10000", "USD"), "contribution_margin": Decimal("0.40"),
            "roas_before": Decimal("1.8"), "roas_after": Decimal("2.3"),
            "cac_before": Money("25", "USD"), "cac_after": Money("18", "USD"),
            "delivery_hours": Decimal("24"), "capacity_hours": Decimal("160"),
        },
    )
    result = engagement.to_dict()
    assert result["status"] == "ready_for_client_service"
    assert Decimal(result["economics"]["incremental_contribution"]["amount"]) == Decimal("500")
    assert result["economics"]["orders_required_to_recover_fee"] != "unknown"


# ---------------------------------------------------------------------------
# B. Evidence assertions
# ---------------------------------------------------------------------------


def test_fixture_evidence_cannot_become_live_validation_end_to_end():
    # Every gate satisfied, but evidence_state is "fixture" (the solar
    # scenario also fails real gates; this isolates the evidence-mode
    # ceiling itself by re-running promotion directly with all gates open).
    from evaluation.commerce.canonical import CommercialOwnership, OwnershipAssignment
    from evaluation.commerce.promotion import GATE_IDS, evaluate_promotion

    fully_known = CommercialOwnership(*(OwnershipAssignment(role, "Acme") for role in (
        "merchant_of_record", "fulfillment_owner", "warranty_owner",
        "return_owner", "support_owner", "payment_collection_owner",
    )))
    decision = evaluate_promotion(
        "fixture-candidate", "scale_candidate",
        gate_satisfaction={gate: True for gate in GATE_IDS},
        evidence_state="fixture", ownership=fully_known,
    )
    assert decision.achievable_stage == "economics_screened"
    assert not decision.promoted


def test_manual_import_evidence_stays_visibly_manual_through_the_kernel():
    solar = solar_4g_security_blocked_candidate()
    result = run_dry_run_lifecycle(solar).economics
    # The scenario's own evidence refs are tagged manual_csv_import/fixture;
    # the kernel must echo that classification back, never silently upgrade
    # it to "observed"/"verified".
    source_types = {ref.source_type for ref in result.evidence_refs}
    assert "manual_csv_import" in source_types
    assert result.evidence_state != "verified"
    assert result.evidence_state != "observed"


def test_consumer_attention_never_substitutes_for_supplier_evidence():
    # The promotion gate vocabulary keeps "customer_facing_promise" (a
    # consumer-facing evidence gate) and "supplier_permission" (a supplier
    # evidence gate) fully independent -- satisfying one must never satisfy
    # the other.
    from evaluation.commerce.promotion import evaluate_promotion

    decision = evaluate_promotion(
        "attention-only-candidate", "supplier_terms_pending",
        gate_satisfaction={"exact_sku": True, "customer_facing_promise": True, "economics": True},
        evidence_state="observed",
    )
    assert "supplier_permission" in decision.blockers


def test_stale_evidence_cannot_promote_an_opportunity():
    from datetime import datetime, timedelta, timezone

    stale_quality = DataQuality(provenance="live", attribution="attributed", observed_at=datetime.now(timezone.utc) - timedelta(days=30))
    product = ProductCandidate("stale-product", "Stale Widget", selling_price=40.0, quality=stale_quality)
    offer = SupplierOffer("supplier-1", "stale-product", unit_cost=10.0, quality=stale_quality)
    readiness = evaluate_product(product, offer)
    assert not readiness.launchable
    assert "stale_data" in readiness.reasons


def test_conflicting_evidence_remains_visible_not_averaged_away():
    from backend.economics.kernel import EvidenceRef, UnitEconomicsAssumptions, calculate_unit_economics

    strong = EvidenceRef("ev-strong", evidence_state="verified")
    weak = EvidenceRef("ev-weak", evidence_state="unknown")
    result = calculate_unit_economics(
        Money("50", "USD", evidence_ref=strong), Money("20", "USD", evidence_ref=weak),
        assumptions=UnitEconomicsAssumptions(evidence_refs=(strong, weak)),
    )
    # The weaker of the two conflicting evidence states must dominate the
    # aggregate classification -- it must not be hidden by the stronger one.
    assert result.evidence_state == "unknown"
    assert {ref.evidence_id for ref in result.evidence_refs} == {"ev-strong", "ev-weak"}


def test_missing_critical_costs_are_reported_missing_not_zeroed_silently():
    from backend.economics.kernel import calculate_unit_economics

    result = calculate_unit_economics(Money("50", "USD"), Money("20", "USD"))
    assert "supplier_shipping" in result.missing_inputs
    assert "return_rate" in result.missing_inputs
    # The zeroed placeholder is present (so the math can run), but it must
    # never be mistaken for an observed zero-cost input.
    assert result.supplier_shipping.amount == Decimal("0")
    assert result.supplier_shipping.source == "assumed_supplier_shipping"


def test_usd_never_silently_becomes_mxn_in_a_full_scenario():
    from backend.economics.kernel import CurrencyMismatchError, MarketLane

    scenario = hydroponics_positive_candidate()
    mxn_lane = MarketLane("mx-lane", "MX", "MX", "MX-CDMX", "MX", currency="MXN")
    with pytest.raises(CurrencyMismatchError):
        run_dry_run_lifecycle(
            scenario.__class__(
                **{**scenario.__dict__, "lane": mxn_lane},
            )
        )


def test_absent_return_and_support_ownership_blocks_readiness():
    for builder in (smart_pet_support_burden_candidate, high_ticket_deferred_candidate):
        report = run_dry_run_lifecycle(builder())
        assert report.achievable_stage not in {"launch_draft", "experiment_ready", "live_sales_validated", "scale_candidate"}
        assert not report.promoted_to_launch


def test_negative_downside_blocks_promotion():
    report = run_dry_run_lifecycle(commodity_electronics_rejected_candidate())
    assert report.economics.contribution_margin is not None and report.economics.contribution_margin < 0
    assert not report.promoted_to_launch
    assert "economics" in report.promotion.blockers


def test_live_actions_remain_blocked_without_approval():
    request = ExecutionDecisionRequest(
        request_id="req-1", action_type="launch_ad_experiment", domain="growth",
        owner_department="marketing", workspace_id="ws-hydroponics_positive_candidate",
        requested_amount=500.0, hypothesis="hook A beats hook B", success_metric="roas",
        kill_threshold=1.0, approval_state="not_requested",
    )
    result = evaluate_execution_request(request)
    assert result.outcome == "requires_approval"
    assert any(item.approval_type == "ad_launch" for item in result.approvals)

    approved = evaluate_execution_request(
        ExecutionDecisionRequest(**{**request.__dict__, "approval_state": "approved"})
    )
    assert approved.outcome != "requires_approval"


# ---------------------------------------------------------------------------
# C. Event and replay assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder", SCENARIO_BUILDERS, ids=[b.__name__ for b in SCENARIO_BUILDERS])
def test_running_a_scenario_twice_is_byte_identical(builder):
    first_events, _ = _events_for(builder, workspace_id="ws-replay")
    second_events, _ = _events_for(builder, workspace_id="ws-replay")
    assert [event.replay_hash() for event in first_events] == [event.replay_hash() for event in second_events]
    assert replay_summary(first_events)["hash_sequence"] == replay_summary(second_events)["hash_sequence"]


def test_event_ordering_is_stable_and_ids_are_unique():
    events, _ = _events_for(hydroponics_positive_candidate, workspace_id="ws-order")
    ids = [event.event_id for event in events]
    assert len(ids) == len(set(ids))
    timestamps = [event.occurred_at for event in events]
    assert timestamps == sorted(timestamps)


def test_duplicate_evidence_reference_does_not_duplicate_the_decision():
    from backend.economics.kernel import EvidenceRef, UnitEconomicsAssumptions, calculate_unit_economics

    ref = EvidenceRef("ev-dup", evidence_state="observed")
    once = calculate_unit_economics(Money("50", "USD"), Money("20", "USD"), assumptions=UnitEconomicsAssumptions(evidence_refs=(ref,)))
    twice = calculate_unit_economics(Money("50", "USD"), Money("20", "USD"), assumptions=UnitEconomicsAssumptions(evidence_refs=(ref, ref)))
    # Supplying the same evidence reference twice must not change the
    # computed economics -- only the deduplicated evidence set may differ.
    assert once.contribution_before_cac.amount == twice.contribution_before_cac.amount
    assert once.evidence_state == twice.evidence_state


def test_duplicate_lifecycle_events_do_not_duplicate_ledger_effects():
    events, _ = _events_for(hydroponics_positive_candidate, workspace_id="ws-dedupe")
    doubled = events + events  # simulate a re-delivered event stream
    deduped = list({event.event_id: event for event in doubled}.values())
    assert len(deduped) == len(events)
    assert [event.replay_hash() for event in deduped] == [event.replay_hash() for event in events]


def test_timestamps_are_explicit_and_deterministic_not_wall_clock():
    events, _ = _events_for(hydroponics_positive_candidate, workspace_id="ws-time")
    assert events[0].occurred_at == 0.0
    # Re-running with the same occurred_at base must reproduce identical
    # timestamps -- nothing in the projection reads the wall clock.
    events_again, _ = _events_for(hydroponics_positive_candidate, workspace_id="ws-time")
    assert [event.occurred_at for event in events] == [event.occurred_at for event in events_again]


def test_no_raw_payloads_or_secrets_persist_in_the_event_trail():
    events, _ = _events_for(solar_4g_security_blocked_candidate, workspace_id="ws-privacy-check")
    for event in events:
        blob = str(event.to_dict()).lower()
        assert "api_key" not in blob and "secret" not in blob and "password" not in blob and "-----begin" not in blob


# ---------------------------------------------------------------------------
# D. Workspace and export assertions
# ---------------------------------------------------------------------------


def test_client_safe_export_removes_internal_formulas_and_source_code():
    leaky_payload = {
        "status": "scale_candidate",
        "internal_scoring_formula": "contribution_before_cac = net_sales - costs",
        "source_code": "def calculate_unit_economics(...): ...",
    }
    findings = check_workspace_leakage(leaky_payload, client_safe=True)
    assert any(item.status == "hard_block" for item in findings)

    client_safe_payload = {"status": "scale_candidate", "blockers": [], "next_actions": ["approve launch draft"]}
    assert check_workspace_leakage(client_safe_payload, client_safe=True) == ()


def test_forged_cross_client_identity_is_rejected():
    forged_payload = {"workspace_id": "ws-a", "note": "copied from other_client workspace ws-b"}
    findings = check_workspace_leakage(forged_payload, client_safe=True)
    assert any(item.status == "hard_block" for item in findings)


def test_report_generation_is_deterministic_for_the_same_scenario():
    report_a = run_dry_run_lifecycle(hydroponics_positive_candidate())
    report_b = run_dry_run_lifecycle(hydroponics_positive_candidate())
    assert report_a.to_dict() == report_b.to_dict()


def test_internal_and_client_workspaces_use_disjoint_artifact_paths(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    internal = registry.register(ClientWorkspace(name="internal-marketos", workspace_type="internal"))
    client = registry.register(ClientWorkspace(name="client-ecommerce", workspace_type="client_service"))
    internal_store = ArtifactStore(internal, registry)
    client_store = ArtifactStore(client, registry)
    internal_path = internal_store.path_for("exp-1", "result.json")
    client_path = client_store.path_for("exp-1", "result.json")
    assert internal_path != client_path


def test_artifact_store_path_escape_is_rejected(tmp_path):
    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    client = registry.register(ClientWorkspace(name="client-ecommerce", workspace_type="client_service"))
    store = ArtifactStore(client, registry)
    with pytest.raises(ValueError, match="invalid experiment_id"):
        store.path_for("../../../../../../../../tmp", "escape.json")


_CONSOLIDATED_REPLAY_FIXTURES = (
    ("hydroponics_promising.json", "hydroponics_positive_candidate"),
    ("smart_pet_support_risk.json", "smart_pet_support_burden_candidate"),
    ("solar_4g_blocked.json", "solar_4g_security_blocked_candidate"),
    ("commodity_electronics_rejected.json", "commodity_electronics_rejected_candidate"),
    ("walking_pad_deferred.json", "high_ticket_deferred_candidate"),
)

_EXPECTED_COMMERCE_STEPS = (
    "evidence", "supplier_offer", "market_lane", "unit_economics", "competition",
    "promotion_gate", "offer", "experiment_draft", "campaign_draft", "simulated_order",
    "supplier_dispatch_draft", "tracking_draft", "delivery", "return_rma",
    "contribution_reconciliation",
)

_EXPECTED_FULFILLMENT_STATES = (
    "order_received", "payment_authorized", "payment_captured", "supplier_order_drafted",
    "supplier_order_approved", "supplier_order_submitted", "supplier_accepted", "stock_confirmed",
    "tracking_pending", "in_transit", "delivered", "return_requested", "rma_opened",
    "return_in_transit", "return_received", "refund_requested", "refund_completed",
    "contribution_reconciled",
)


@pytest.mark.parametrize("fixture_name,builder_name", _CONSOLIDATED_REPLAY_FIXTURES)
def test_consolidated_replay_carries_research_through_mexico_fulfillment_and_safe_export(fixture_name, builder_name):
    result = run_consolidated_scenario(fixture_name, builder_name)

    assert result["research"]["market_lane"]["destination_country"] == "Mexico"
    assert result["research"]["market_lane"]["currency"] == "MXN"
    assert result["evidence_classes"]["runner"] == "actual_executed"
    assert result["evidence_classes"]["research_input"] == "fixture"
    assert result["evidence_classes"]["supplier_evidence"] in {"manual_import", "unavailable"}
    assert result["evidence_classes"]["economics"] == (
        "derived" if result["supplier_offer"] is not None else "unavailable"
    )
    assert result["evidence_classes"]["economics_calculation"] == "actual_executed"
    assert result["evidence_classes"]["commerce_lifecycle"] == "simulated_or_planned"
    assert result["evidence_classes"]["fulfillment_lifecycle"] == "simulated_or_planned"
    assert result["evidence_classes"]["governor"] == "simulated_or_planned"
    assert result["evidence_classes"]["approval_ledger"] == "simulated_or_planned"
    assert result["evidence_classes"]["trustos_export"] == "actual_executed"
    assert result["evidence_classes"]["ci"] == "ci_unavailable"
    assert result["commerce"]["commerce_packet"]["dry_run"] is True
    assert result["commerce"]["commerce_packet"]["live_actions_taken"] is False
    assert tuple(step["step"] for step in result["commerce"]["steps"]) == _EXPECTED_COMMERCE_STEPS
    assert all(set(step) == {"step", "status", "detail", "reasons"} for step in result["commerce"]["steps"])
    assert tuple(result["fulfillment"]["state_path"]) == _EXPECTED_FULFILLMENT_STATES
    assert result["fulfillment"]["state_path"][-1] == "contribution_reconciled"
    assert {"return_requested", "rma_opened", "contribution_reconciled"} <= set(result["fulfillment"]["state_path"])
    assert result["fulfillment"]["live_action_allowed"] is False
    assert result["fulfillment"]["external_mutations"] is False
    if result["supplier_offer"] is None:
        assert "unknown_cost:product_cost" in result["fulfillment"]["reserve_classifications"]
        assert "unknown_cost:supplier_shipping" in result["fulfillment"]["reserve_classifications"]
    assert result["event_summary"]["sequence_issues"] == []
    assert result["event_summary"]["live_authority_violations"] == []
    assert "ledger" not in result["event_summary"]
    assert result["event_count"] == result["event_summary"]["event_count"] == 37
    assert len(result["event_summary"]["hash_sequence"]) == 37
    assert len(result["event_ids"]) == len(set(result["event_ids"])) == 37
    assert result["event_replay_hashes"] == result["event_summary"]["hash_sequence"]
    assert len(result["replay_hash"]) == 64
    assert result["second_append_idempotent_count"] == result["event_count"]
    assert result["first_append_count"] == result["event_count"]
    assert result["governor"]["simulated_only"] is True
    assert result["governor"]["outcome"] == "soft_block"
    assert result["governor"]["approvals"][0]["approval_type"] == "approval_ledger"
    assert result["approval_ledger"]["report_version"] == "companyos-approval-ledger-v1"
    assert result["approval_ledger"]["simulation_count"] == 1
    assert result["approval_ledger"]["simulation_results"] == [{
        "action": "launch_ad",
        "result": "would_be_blocked_by_policy",
        "can_be_approved_now": False,
    }]
    assert result["approval_ledger"]["external_action_authorized"] is False
    assert result["approval_ledger"]["safety_summary"]["read_only"] is True
    assert result["approval_ledger"]["safety_summary"]["external_action_performed"] is False
    assert result["approval_ledger"]["safety_summary"]["network_calls"] is False
    assert result["approval_ledger"]["safety_summary"]["mutated"] is False
    supplier_offer_step = result["commerce"]["steps"][1]["detail"]["supplier_offer"]
    if result["supplier_offer"] is None:
        assert supplier_offer_step is None
    else:
        assert supplier_offer_step["evidence_ref"]["evidence_state"] == "fixture"
    assert result["commerce"]["steps"][2]["detail"]["currency"] == "MXN"
    assert result["launch_authorized"] is False
    assert result["provider_calls"] is False
    assert result["credentials_used"] is False
    assert result["database_writes"] is False
    assert result["client_export"]["redaction_status"] == "validated_no_sensitive_fields"
    assert set(result["client_export"]["payload"]) <= {
        "workspace_id", "status", "blockers", "evidence_required", "approvals_required", "next_actions",
    }


def test_consolidated_replay_is_byte_identical_and_missing_supplier_proof_stays_blocked():
    first = run_consolidated_scenario("walking_pad_deferred.json", "high_ticket_deferred_candidate")
    second = run_consolidated_scenario("walking_pad_deferred.json", "high_ticket_deferred_candidate")

    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(second, sort_keys=True, separators=(",", ":"))
    assert first["event_ids"] == second["event_ids"]
    assert first["event_replay_hashes"] == second["event_replay_hashes"]
    assert first["replay_hash"] == second["replay_hash"]
    assert first["supplier_offer"] is None
    assert "supplier_offer_evidence_missing" in first["research"]["blockers"]
    assert first["commerce"]["promoted_to_launch"] is False


def test_missing_supplier_cost_is_unavailable_in_report_and_canonical_economics_event(monkeypatch):
    from backend.events.repository import InMemoryEventRepository

    captured_events = []
    append_many = InMemoryEventRepository.append_many

    def capture_events(repository, events):
        rows = tuple(events)
        captured_events.extend(rows)
        return append_many(repository, rows)

    monkeypatch.setattr(InMemoryEventRepository, "append_many", capture_events)
    result = run_consolidated_scenario(
        "walking_pad_deferred.json", "high_ticket_deferred_candidate"
    )

    economics_step = next(
        step for step in result["commerce"]["steps"] if step["step"] == "unit_economics"
    )
    assert economics_step["status"] == "unavailable"
    assert economics_step["detail"]["calculation_execution"] == "actual_executed"
    assert economics_step["detail"]["evidence_state"] == "missing"
    assert {"product_cost", "supplier_shipping"} <= set(
        economics_step["detail"]["missing_inputs"]
    )
    assert "contribution_margin" not in economics_step["detail"]
    assert "contribution_before_cac" not in economics_step["detail"]
    assert result["commerce"]["commerce_packet"]["economics"]["status"] == "unavailable"
    assumptions = result["commerce"]["commerce_packet"]["assumptions"]
    assert "supplier_shipping" not in assumptions
    assert "cac" not in assumptions
    assert "payment_fee_fixed" not in assumptions
    assert result["evidence_classes"]["supplier_evidence"] == "unavailable"
    assert result["evidence_classes"]["economics"] == "unavailable"
    assert result["evidence_classes"]["economics_calculation"] == "actual_executed"
    assert result["evidence_classes"]["runner"] == "actual_executed"
    assert result["evidence_classes"]["trustos_export"] == "actual_executed"
    assert result["evidence_classes"]["external_validation"] == "unavailable"
    assert result["evidence_classes"]["commerce_lifecycle"] == "simulated_or_planned"
    assert result["evidence_classes"]["ci"] == "ci_unavailable"
    assert "economics" in result["commerce"]["promotion"]["blockers"]
    assert result["commerce"]["promoted_to_launch"] is False

    economics_event = next(
        event for event in captured_events
        if event.event_type == "commerce_dry_run_step_unit_economics"
    )
    assert economics_event.payload["status"] == "unavailable"
    assert economics_event.payload["detail"]["evidence_state"] == "missing"
    assert "contribution_before_cac" not in economics_event.payload["detail"]
    assert "amount" not in economics_event.payload["detail"]
    event_index = result["event_ids"].index(economics_event.event_id)
    assert result["event_replay_hashes"][event_index] == economics_event.replay_hash()


def test_missing_supplier_shipping_is_unavailable_but_explicit_zero_is_preserved(monkeypatch):
    import scripts.research_to_decision as research_to_decision
    from scripts.run_commercial_replay_integration import _missing_supplier_cost_inputs
    from backend.events.repository import InMemoryEventRepository

    captured_events = []
    append_many = InMemoryEventRepository.append_many

    def capture_events(repository, events):
        rows = tuple(events)
        captured_events.extend(rows)
        return append_many(repository, rows)

    monkeypatch.setattr(InMemoryEventRepository, "append_many", capture_events)
    offer = {"price": {"amount": "12.50"}}
    assert _missing_supplier_cost_inputs(offer, None) == ("supplier_shipping",)
    assert _missing_supplier_cost_inputs(offer, "0") == ()
    assert _missing_supplier_cost_inputs(
        {"price": {"amount": None}}, "0"
    ) == ("product_cost",)

    build = research_to_decision.build_research_to_decision

    def without_shipping(manifest, *, base_dir):
        report = build(manifest, base_dir=base_dir)
        supplier_offer = next(
            item for item in report["appendix"]["supplier_offers"]
            if item["candidate_id"] == "hydroponics-kit"
        )
        supplier_offer["shipping"]["cost"] = None
        return report

    monkeypatch.setattr(
        research_to_decision, "build_research_to_decision", without_shipping
    )
    result = run_consolidated_scenario(
        "hydroponics_promising.json", "hydroponics_positive_candidate"
    )
    economics_step = next(
        step for step in result["commerce"]["steps"] if step["step"] == "unit_economics"
    )
    assert result["supplier_offer"] is not None
    assert economics_step["status"] == "unavailable"
    assert "supplier_shipping" in economics_step["detail"]["missing_inputs"]
    assert "contribution_margin" not in economics_step["detail"]
    assert result["evidence_classes"]["supplier_evidence"] == "manual_import"
    assert result["evidence_classes"]["economics"] == "unavailable"
    assert "economics" in result["commerce"]["promotion"]["blockers"]
    assert "unknown_cost:supplier_shipping" in result["fulfillment"]["reserve_classifications"]
    assert result["commerce"]["commerce_packet"]["economics"]["status"] == "unavailable"
    assert "supplier_shipping" not in result["commerce"]["commerce_packet"]["assumptions"]
    assert "ledger" not in result["event_summary"]
    economics_event = next(
        event for event in captured_events
        if event.event_type == "commerce_dry_run_step_unit_economics"
    )
    assert economics_event.payload["status"] == "unavailable"
    assert economics_event.payload["detail"]["evidence_state"] == "missing"
    assert "supplier_shipping" in economics_event.payload["detail"]["missing_inputs"]
    assert "amount" not in economics_event.payload["detail"]
    assert "contribution_before_cac" not in economics_event.payload["detail"]
    export_json = json.dumps(result["client_export"]["payload"], sort_keys=True)
    assert result["client_export"]["payload"]["status"] == "blocked"
    assert "economics" not in result["client_export"]["payload"]
    assert "supplier_shipping" not in export_json
    assert "contribution" not in export_json

    def with_zero_shipping(manifest, *, base_dir):
        report = build(manifest, base_dir=base_dir)
        supplier_offer = next(
            item for item in report["appendix"]["supplier_offers"]
            if item["candidate_id"] == "hydroponics-kit"
        )
        supplier_offer["shipping"]["cost"] = "0"
        return report

    monkeypatch.setattr(
        research_to_decision, "build_research_to_decision", with_zero_shipping
    )
    zero_result = run_consolidated_scenario(
        "hydroponics_promising.json", "hydroponics_positive_candidate"
    )
    zero_economics = next(
        step for step in zero_result["commerce"]["steps"]
        if step["step"] == "unit_economics"
    )
    assert zero_economics["status"] == "simulated"
    assert zero_result["evidence_classes"]["economics"] == "derived"
    assert zero_result["commerce"]["commerce_packet"]["assumptions"][
        "supplier_shipping"
    ]["amount"] == "0"


@pytest.mark.parametrize(
    ("product_cost_value", "shipping_value", "expected_status"),
    ((None, "25", "unavailable"), ("0", "0", "simulated"), ("100", "25", "simulated")),
)
def test_product_cost_missing_zero_and_positive_remain_distinct_in_serialized_replay(
    monkeypatch, product_cost_value, shipping_value, expected_status,
):
    import scripts.research_to_decision as research_to_decision
    from backend.events.repository import InMemoryEventRepository

    captured_events = []
    append_many = InMemoryEventRepository.append_many

    def capture_events(repository, events):
        rows = tuple(events)
        captured_events.extend(rows)
        return append_many(repository, rows)

    monkeypatch.setattr(InMemoryEventRepository, "append_many", capture_events)
    build = research_to_decision.build_research_to_decision

    def with_cost_values(manifest, *, base_dir):
        report = build(manifest, base_dir=base_dir)
        candidate_id = manifest["candidates"][0]["candidate_id"]
        offer = next(
            item for item in report["appendix"]["supplier_offers"]
            if item["candidate_id"] == candidate_id
        )
        offer["price"]["amount"] = product_cost_value
        offer["shipping"]["cost"] = shipping_value
        offer["evidence"]["state"] = "fixture"
        manifest["candidates"][0]["target_sell_price"] = "10000"
        return report

    monkeypatch.setattr(
        research_to_decision, "build_research_to_decision", with_cost_values
    )
    result = run_consolidated_scenario(
        "hydroponics_promising.json", "hydroponics_positive_candidate"
    )
    economics_step = next(
        step for step in result["commerce"]["steps"] if step["step"] == "unit_economics"
    )
    economics_event = next(
        event for event in captured_events
        if event.event_type == "commerce_dry_run_step_unit_economics"
    )
    export_json = json.dumps(result["client_export"]["payload"], sort_keys=True)
    result_json = json.dumps(result, sort_keys=True)

    assert economics_step["status"] == expected_status
    assert result["client_export"]["payload"]["status"] == "blocked"
    assert "contribution" not in export_json
    assert "product_cost" not in export_json
    assert "supplier_shipping" not in export_json
    if product_cost_value is None:
        assert economics_step["detail"]["evidence_state"] == "missing"
        assert "product_cost" in economics_step["detail"]["missing_inputs"]
        assert "contribution_before_cac" not in economics_step["detail"]
        assert "amount" not in economics_event.payload["detail"]
        assert "economics" in result["commerce"]["promotion"]["blockers"]
        assert "unknown_cost:product_cost" in result["fulfillment"]["reserve_classifications"]
        assert result["commerce"]["commerce_packet"]["economics"]["status"] == "unavailable"
        assert "contribution_before_cac" not in result_json
        assert "contribution_profit" not in result_json
    else:
        economics = result["commerce"]["commerce_packet"]["economics"]
        assert economics["product_cost"]["amount"] == product_cost_value
        assert economics["product_cost"]["source"] == "fixture"
        assert economics["product_cost"]["evidence_state"] == "fixture"
        assert economics["supplier_shipping"]["amount"] == shipping_value
        assert economics["supplier_shipping"]["evidence_state"] == "fixture"
        assert economics_event.payload["status"] == "simulated"
        assert economics_event.payload["detail"]["contribution_before_cac"][
            "evidence_state"
        ] == "fixture"
        assert result["evidence_classes"]["economics"] == "derived"
        assert result["launch_authorized"] is False


@pytest.mark.parametrize("fixture_name", ("stale_offer.json", "conflicting_quotes.json"))
def test_quarantined_supplier_offers_cannot_supply_replay_economics(
    monkeypatch, fixture_name,
):
    import scripts.research_to_decision as research_to_decision

    build = research_to_decision.build_research_to_decision

    def complete_quarantined_offer(manifest, *, base_dir):
        report = build(manifest, base_dir=base_dir)
        candidate_id = manifest["candidates"][0]["candidate_id"]
        offers = [
            item for item in report["appendix"]["supplier_offers"]
            if item["candidate_id"] == candidate_id
        ]
        assert offers and all(item["status"] == "quarantined" for item in offers)
        for offer in offers:
            offer["shipping"]["cost"] = "1"
            offer["evidence"]["state"] = "fixture"
        manifest["candidates"][0]["target_sell_price"] = "10000"
        return report

    monkeypatch.setattr(
        research_to_decision, "build_research_to_decision", complete_quarantined_offer
    )
    result = run_consolidated_scenario(
        fixture_name, "hydroponics_positive_candidate"
    )
    economics_step = next(
        step for step in result["commerce"]["steps"] if step["step"] == "unit_economics"
    )
    export_json = json.dumps(result["client_export"]["payload"], sort_keys=True)

    assert result["supplier_offer"] is None
    assert result["evidence_classes"]["supplier_evidence"] == "unavailable"
    assert result["evidence_classes"]["economics"] == "unavailable"
    assert economics_step["status"] == "unavailable"
    assert economics_step["detail"]["evidence_state"] == "missing"
    assert {"product_cost", "supplier_shipping"} <= set(
        economics_step["detail"]["missing_inputs"]
    )
    assert "economics" in result["commerce"]["promotion"]["blockers"]
    assert result["commerce"]["promoted_to_launch"] is False
    assert result["client_export"]["payload"]["status"] == "blocked"
    assert "contribution" not in export_json
    assert "product_cost" not in export_json
    assert "supplier_shipping" not in export_json
    assert any("supplier_offer:" in blocker for blocker in result["research"]["blockers"])


@pytest.mark.parametrize("fixture_name,builder_name", _CONSOLIDATED_REPLAY_FIXTURES)
def test_each_consolidated_scenario_has_stable_canonical_event_replay_identity(fixture_name, builder_name):
    first = run_consolidated_scenario(fixture_name, builder_name)
    second = run_consolidated_scenario(fixture_name, builder_name)

    assert first["event_count"] == 37
    assert first["event_ids"] == second["event_ids"]
    assert first["event_replay_hashes"] == second["event_replay_hashes"]
    assert first["event_replay_hashes"] == first["event_summary"]["hash_sequence"]
    assert first["replay_hash"] == second["replay_hash"]


_REQUIRED_EVIDENCE_BLOCKERS = (
    ("smart_pet_support_risk.json", "smart_pet_support_burden_candidate", "support_owner"),
    ("solar_4g_blocked.json", "solar_4g_security_blocked_candidate", "compliance"),
    ("commodity_electronics_rejected.json", "commodity_electronics_rejected_candidate", "economics"),
    ("walking_pad_deferred.json", "high_ticket_deferred_candidate", "supplier_offer_evidence_missing"),
    ("walking_pad_deferred.json", "high_ticket_deferred_candidate", "return_route"),
    ("walking_pad_deferred.json", "high_ticket_deferred_candidate", "warranty_route"),
)


def test_dogfood_summary_exposes_the_canonical_evidence_vocabulary():
    summary = run_scenarios()

    assert summary["result"] == "actual"
    assert summary["evidence_classification"] == "fixture"
    assert summary["evidence_class_vocabulary"] == list(EVIDENCE_CLASS_VOCABULARY)
    assert len(summary["rows"]) == 5
    assert all(row["evidence_classes"]["runner"] == "actual_executed" for row in summary["rows"])
    assert all(row["evidence_classes"]["ci"] == "ci_unavailable" for row in summary["rows"])


@pytest.mark.parametrize("fixture_name,builder_name,required_blocker", _REQUIRED_EVIDENCE_BLOCKERS)
def test_positive_signals_cannot_override_missing_required_commercial_evidence(
    fixture_name, builder_name, required_blocker,
):
    result = run_consolidated_scenario(fixture_name, builder_name)
    blockers = set(result["research"]["blockers"])
    blockers.update(result["commerce"]["promotion"]["blockers"])
    blockers.update(result["fulfillment"]["blockers"])

    assert required_blocker in blockers
    assert result["commerce"]["promoted_to_launch"] is False
    assert result["launch_authorized"] is False
    assert result["client_export"]["payload"]["status"] == "blocked"


def test_consolidated_export_rejects_unsafe_status_claim(tmp_path):
    from backend.workspaces.client_workspace import ClientWorkspace
    from backend.workspaces.registry import WorkspaceRegistry
    from evaluation.trustos.client_workspace_isolation import ClientWorkspaceExportError, export_client_evidence

    registry = WorkspaceRegistry(str(tmp_path / "workspaces.json"))
    workspace = registry.register(ClientWorkspace(workspace_id="workspace_unsafe_fixture", name="unsafe-fixture", workspace_type="client_service"))
    with pytest.raises(ClientWorkspaceExportError, match="client evidence export rejected"):
        export_client_evidence(
            workspace=workspace,
            registry=registry,
            provenance="fixture://commercial-replay/unsafe",
            evidence_state="requires_review",
            payload={
                "workspace_id": workspace.workspace_id,
                "status": "live_validated",
                "blockers": [],
                "evidence_required": [],
                "approvals_required": [],
                "next_actions": [],
            },
        )
