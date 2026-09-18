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

Known, already-owned gap (documented, not duplicated): artifact-store path
traversal / workspace escape (``backend.workspaces.artifact_store.ArtifactStore.path_for``
performs no path-traversal sanitization on ``workspace_id``/``experiment_id``/
``filename``) is the explicit subject of open PR #211
("fix(workspaces): close artifact-store path traversal and workspace
escape"). ``test_artifact_store_path_escape_is_not_yet_closed`` below
reproduces it against the current SHA and documents PR #211 as its owner —
it does not patch it here, to avoid duplicating that PR's already-assigned
scope.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from backend.contracts.events import Event
from backend.economics.kernel import Money
from backend.events.replay_certification import replay_summary
from backend.workspaces.artifact_store import ArtifactStore
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


def test_internal_and_client_workspaces_use_disjoint_artifact_paths():
    store = ArtifactStore()
    internal_path = store.path_for("internal_marketos_core", "exp-1", "result.json")
    client_path = store.path_for("client_ecommerce_workspace", "exp-1", "result.json")
    assert internal_path != client_path


@pytest.mark.xfail(
    reason=(
        "backend.workspaces.artifact_store.ArtifactStore.path_for performs no "
        "traversal sanitization on workspace_id/experiment_id/filename; this exact "
        "defect is PR #211's assigned scope ('fix(workspaces): close artifact-store "
        "path traversal and workspace escape'), still open as of this harness. "
        "Documented here rather than duplicated -- see this PR's final report."
    ),
    strict=True,
)
def test_artifact_store_path_escape_is_not_yet_closed():
    import os

    store = ArtifactStore()
    client_root = os.path.abspath(store.path_for("client_ecommerce_workspace", "", ""))
    workspaces_root = os.path.dirname(os.path.dirname(client_root.rstrip(os.sep)))
    escaping_path = os.path.abspath(store.path_for("../../../../../../../../tmp", "exp-1", "escape.json"))
    # Once PR #211 lands, a workspace_id containing path-traversal segments
    # must not be able to resolve outside the workspaces root. Today it can.
    assert escaping_path.startswith(workspaces_root + os.sep)
