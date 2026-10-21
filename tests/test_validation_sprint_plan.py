"""Plan-only validation sprint preflight: deterministic, side-effect free, governed, non-authorizing."""
from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from backend.discovery import validation_sprint_registry as vsr
from backend.discovery import validation_sprint_runner as runner
from backend.discovery.opportunity_pipeline import Opportunity
from backend.discovery.opportunity_registry import OpportunityRegistry
from backend.discovery.validation_scorecard import build_validation_scorecard
from backend.discovery.validation_sprint import ValidationScorecard
from backend.discovery.validation_sprint_runner import plan_validation_sprint
from evaluation.companyos.resource_execution_governor import ResourceBudget, RunawayGuardPolicy

ROOT = Path(__file__).resolve().parents[1]
LEARNING_FIXTURE = ROOT / "tests" / "fixtures" / "validation_sprint" / "learning_prior_kill.json"
FULL_METADATA = {"price": 40, "product": {"sku": "synthetic-desk-clamp-lamp"}, "offer": {"price": 40}}
CANARY = "SYNTHETIC-CANARY-VALUE-7f3a"
PLANNED_SERVICES = ["product_research", "customer_intelligence", "profit_stack_advisor"]


class Evidence:
    def __init__(self, evidence_id, provenance=None):
        self.evidence_id = evidence_id
        self.provenance = provenance or {}


POOL = [Evidence("ev-1")]


def opp(opportunity_id, score=80.0, *, stage="validation_ready", evidence=("ev-1",), metadata=None, workspace="default", name=None, category="Desk", kind="product_hypothesis"):
    return Opportunity(
        opportunity_id, workspace, kind, name or f"Name {opportunity_id}", category, stage=stage,
        score=score, confidence=0.8, evidence_ids=list(evidence),
        metadata=dict(FULL_METADATA) if metadata is None else dict(metadata),
    )


def _plan(candidates, **kwargs):
    """The shared evidence pool holds ev-1 unless a test supplies its own pool."""
    kwargs.setdefault("evidence_records", POOL)
    return plan_validation_sprint(candidates, **kwargs)


def learning_context():
    return json.loads(LEARNING_FIXTURE.read_text(encoding="utf-8"))


def _budget(soft, hard=20.0, limit=20.0, approval=10.0):
    return ResourceBudget("report_generation_quota", "finance", "internal-companyos", "monthly", limit, 0.0, 0.0, "reports", hard, soft, approval)


def _forbidden(name):
    def _raise(*args, **kwargs):
        raise AssertionError(f"plan-only path invoked {name}")
    return _raise


@pytest.fixture
def no_side_effects(monkeypatch):
    """Every executor, registry write, stage transition, and run entry point fails the test if reached."""
    monkeypatch.setattr(runner, "run_validation_sprint", _forbidden("run_validation_sprint"))
    monkeypatch.setattr(runner, "run_planner_executor_reviewer", _forbidden("run_planner_executor_reviewer"))
    monkeypatch.setattr(runner, "get_validation_sprint_registry", _forbidden("get_validation_sprint_registry"))
    for name in ("register_sprint", "update_sprint", "register_scorecard", "save"):
        monkeypatch.setattr(vsr.ValidationSprintRegistry, name, _forbidden(f"ValidationSprintRegistry.{name}"))
    for name in ("register_opportunity", "update_opportunity", "register_transition", "save"):
        monkeypatch.setattr(OpportunityRegistry, name, _forbidden(f"OpportunityRegistry.{name}"))
    return monkeypatch


# --- determinism -----------------------------------------------------------------------------------


def test_same_inputs_produce_identical_plan_and_id():
    candidates = [opp("opp-a", 80), opp("opp-b", 70)]
    first = _plan(candidates)
    second = _plan(candidates)
    assert first.plan_id == second.plan_id
    assert first.to_dict() == second.to_dict()
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)


def test_permuted_candidates_and_requested_ids_produce_identical_decisions():
    candidates = [opp("opp-a", 80), opp("opp-b", 70), opp("opp-c", 90), opp("opp-d", 65)]
    base = _plan(candidates, requested_ids=["opp-a", "opp-b", "opp-c", "opp-d"])
    shuffled = list(candidates)
    random.Random(7).shuffle(shuffled)
    permuted = _plan(shuffled, requested_ids=["opp-d", "opp-c", "opp-b", "opp-a"])
    assert permuted.to_dict() == base.to_dict()
    assert [t.opportunity_id for t in base.targets] == ["opp-c", "opp-a", "opp-b", "opp-d"]


def test_repeated_requested_id_is_one_target():
    plan = _plan([opp("opp-a")], requested_ids=["opp-a", "opp-a", "opp-a"])
    assert [t.opportunity_id for t in plan.targets] == ["opp-a"]


def test_plan_id_changes_when_governance_policy_changes():
    candidates = [opp("opp-a")]
    default = _plan(candidates)
    tighter = _plan(candidates, budgets=[_budget(soft=5.0)])
    assert default.plan_id != tighter.plan_id
    assert default.plan_id.startswith("vsplan_")


def test_plan_id_changes_when_an_opportunity_field_that_changes_outcomes_changes():
    base = _plan([opp("same", category="Desk")])
    recategorized = _plan([opp("same", category="Kitchen")])
    assert base.plan_id != recategorized.plan_id


def test_duplicate_conflicting_records_are_ineligible_regardless_of_input_order():
    first = opp("dup", 80)
    second = opp("dup", 50, stage="discovered")
    forward = _plan([first, second])
    reverse = _plan([second, first])
    assert forward.to_dict() == reverse.to_dict()
    assert forward.targets[0].reasons == ["duplicate_opportunity_records"]
    assert forward.targets[0].eligible is False


def test_limit_is_bounded_and_applied_before_governance():
    candidates = [opp(f"opp-{i}", 90 - i) for i in range(6)]
    plan = _plan(candidates, limit=2)
    assert [t.opportunity_id for t in plan.targets] == ["opp-0", "opp-1"]


# --- side-effect freedom ---------------------------------------------------------------------------


def test_plan_path_never_reaches_executor_registry_stage_or_run_entry_points(no_side_effects):
    plan = _plan(
        [opp("candidate-a", 80), opp("candidate-b", 70), opp("opp-c", 90, stage="discovered")],
        requested_ids=["candidate-a", "candidate-b", "opp-c", "opp-missing"],
        learning_context=learning_context(),
    )
    assert plan.safety["service_executor_invocations"] == 0
    assert plan.safety["registry_writes"] == 0
    assert plan.safety["opportunity_stage_transitions"] == 0


def test_plan_runs_under_forbidden_side_effects(no_side_effects):
    plan = _plan([opp("safe-a", 80), opp("safe-b", 70)], learning_context=learning_context())
    assert isinstance(plan.to_dict(), dict)


# --- governance ------------------------------------------------------------------------------------


def test_shared_quota_blocks_targets_beyond_the_cycle_limit_in_canonical_order():
    candidates = [opp(f"q-{i}", 90 - i) for i in range(7)]
    plan = _plan(candidates, budgets=[_budget(soft=100.0, hard=100.0, limit=100.0, approval=100.0)])
    statuses = {t.opportunity_id: t.status for t in plan.targets}
    assert [statuses[f"q-{i}"] for i in range(5)] == ["planned"] * 5
    assert [statuses[f"q-{i}"] for i in (5, 6)] == ["blocked", "blocked"]
    blocked = next(t for t in plan.targets if t.opportunity_id == "q-5")
    assert blocked.governor["outcome"] == "soft_block"
    assert "aggregate planned action quota exceeded" in blocked.reasons
    assert plan.governor_summary["consumed_actions"] == 5
    assert plan.governor_summary["consumed_amount"] == 15.0


def test_low_opportunity_score_is_soft_blocked_by_portfolio_threshold():
    plan = _plan([opp("low", 55)])
    target = plan.targets[0]
    assert target.status == "blocked"
    assert target.governor["outcome"] == "soft_block"
    assert target.reasons == ["opportunity score below portfolio threshold"]
    assert plan.status == "blocked"


def test_budget_soft_cap_routes_to_awaiting_approval_with_named_approver():
    plan = _plan([opp("b-1", 90), opp("b-2", 80), opp("b-3", 70)], budgets=[_budget(soft=5.0)])
    assert [t.status for t in plan.targets] == ["planned", "awaiting_approval", "awaiting_approval"]
    approval = plan.approvals_required[0]
    assert approval["approval_type"] == "budget_cap"
    assert approval["approver_role"] == "finance_manager"
    assert plan.status == "partial"
    assert plan.execution_handoff["requires_human_approval"] is True
    assert plan.execution_handoff["payload"]["opportunity_ids"] == ["b-1"]


def test_approvals_are_only_surfaced_for_targets_that_await_them():
    budget = _budget(soft=5.0)
    plan = _plan([opp(f"x-{i}", 90 - i) for i in range(7)], budgets=[budget])
    blocked = [t for t in plan.targets if t.status == "blocked"]
    assert blocked, "the fixture must include a governor-blocked target"
    approved_targets = {row["opportunity_id"] for row in plan.approvals_required}
    assert approved_targets.isdisjoint({t.opportunity_id for t in blocked})
    assert approved_targets == {t.opportunity_id for t in plan.targets if t.status == "awaiting_approval"}


def test_hard_budget_cap_blocks_without_consuming_capacity():
    budget = _budget(soft=5.0, hard=5.0, limit=5.0, approval=5.0)
    plan = _plan([opp("h-1", 90), opp("h-2", 80), opp("h-3", 70)], budgets=[budget])
    assert [t.status for t in plan.targets] == ["planned", "blocked", "blocked"]
    assert "hard cap or aggregate planned budget exceeded" in plan.targets[1].reasons
    assert plan.governor_summary["consumed_amount"] == 3.0
    assert plan.governor_summary["consumed_actions"] == 1


def test_runaway_policy_hard_blocks_the_sprint_step():
    runaway = RunawayGuardPolicy("runaway-test", 1, 2, 10, 3, 5, 10, 2, 20, 300, 25.0, 2, ("stop",), ("summary",))
    plan = _plan([opp("r-1")], runaway=runaway)
    target = plan.targets[0]
    assert target.governor["outcome"] == "hard_block"
    assert target.reasons == ["runaway guard cap exceeded"]
    assert plan.status == "blocked"


def test_empty_candidate_set_is_blocked_with_explicit_reason():
    plan = _plan([])
    assert plan.status == "blocked"
    assert plan.reasons == ["no_validation_targets"]
    assert plan.targets == []


def test_awaiting_target_keeps_its_gap_reasons_alongside_the_approval_reason(monkeypatch):
    monkeypatch.setattr(runner, "build_validation_service_plan", lambda opportunity: ["product_research", "unit_economics"])
    plan = _plan([opp("big", 90), opp("gappy", 80, metadata={"price": 40})], budgets=[_budget(soft=2.0)])
    gappy = next(t for t in plan.targets if t.opportunity_id == "gappy")
    assert gappy.status == "awaiting_approval"
    assert gappy.skipped_services == {"unit_economics": ["offer", "product"]}
    assert gappy.reasons == [
        "soft cap exceeded; finance review required",
        "missing_evidence:offer",
        "missing_evidence:product",
    ]


# --- learning constraints --------------------------------------------------------------------------


def test_prior_kill_constrains_only_the_candidate_it_was_recorded_for():
    plan = _plan(
        [opp("candidate-a", 80), opp("candidate-b", 70)],
        requested_ids=["candidate-a", "candidate-b"],
        learning_context=learning_context(),
    )
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["candidate-a"].status == "blocked"
    assert by_id["candidate-a"].reasons == ["required learning has not been captured"]
    assert by_id["candidate-a"].learning["kill_blocks_resumption"] is True
    assert by_id["candidate-a"].learning["candidate_scoped"] is True
    assert by_id["candidate-b"].status == "planned"
    assert by_id["candidate-b"].learning["previous_learning_required"] is False


def test_acknowledgement_is_per_candidate_not_batch_wide():
    context = learning_context()
    second = {**context["events"][0], "learning_event_id": "fixture-prior-kill-candidate-c", "candidate_id": "candidate-c"}
    context = {"events": [*context["events"], second]}
    plan = _plan(
        [opp("candidate-a", 80), opp("candidate-c", 75)],
        requested_ids=["candidate-a", "candidate-c"],
        learning_context=context,
        acknowledged_learning_for=["candidate-a"],
    )
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["candidate-a"].status == "planned"
    assert by_id["candidate-a"].learning["previous_learning_required"] is True
    assert by_id["candidate-a"].learning["learning_acknowledged"] is True
    assert by_id["candidate-c"].status == "blocked"
    assert by_id["candidate-c"].learning["learning_acknowledged"] is False


def test_acknowledged_learning_stays_visible_on_the_released_target():
    plan = _plan(
        [opp("candidate-a", 80), opp("candidate-b", 70)],
        requested_ids=["candidate-a", "candidate-b"],
        learning_context=learning_context(),
        acknowledged_learning_for=["candidate-a"],
    )
    released = next(t for t in plan.targets if t.opportunity_id == "candidate-a")
    assert released.status == "planned"
    assert released.learning["kill_blocks_resumption"] is True
    assert plan.status == "planned"


def test_malformed_learning_events_fail_closed():
    with pytest.raises(ValueError):
        _plan([opp("opp-a")], learning_context={"events": ["not-a-mapping"]})


def test_learning_context_must_be_a_mapping():
    with pytest.raises(ValueError):
        _plan([opp("opp-a")], learning_context=["not", "a", "mapping"])


# --- missing evidence and inputs ---------------------------------------------------------------------


def test_missing_evidence_is_ineligible_and_never_reaches_the_governor():
    plan = _plan([opp("no-evidence", evidence=())])
    target = plan.targets[0]
    assert target.eligible is False and target.status == "ineligible"
    assert target.reasons == ["no_evidence_recorded"]
    assert target.governor == {}
    assert "record_evidence:no-evidence" in plan.next_safe_steps


def test_unresolved_evidence_reference_fails_closed():
    plan = _plan([opp("ghost", evidence=("ev-ghost",))], evidence_records=POOL)
    target = plan.targets[0]
    assert target.eligible is False
    assert target.reasons == ["unresolved_evidence_reference:ev-ghost"]
    assert target.governor == {}
    assert "resolve_evidence_reference:ghost" in plan.next_safe_steps


def test_preview_uses_only_the_candidates_own_evidence_so_synthetic_evidence_is_not_masked():
    synthetic = Evidence("ev-syn", provenance={"not_real_market_data": True})
    real = Evidence("ev-real", provenance={})
    plan = _plan(
        [opp("syn", evidence=("ev-syn",))],
        evidence_records=[synthetic, real],
    )
    preview = plan.targets[0].scorecard_preview
    assert "synthetic_only_evidence" in preview["risk_flags"]


@pytest.mark.parametrize("stage", ["discovered", "evidence_requested", "evidence_enriched", "launch_candidate", "rejected", "archived"])
def test_only_validation_ready_opportunities_are_eligible(stage):
    plan = _plan([opp("staged", stage=stage)], requested_ids=["staged"])
    target = plan.targets[0]
    assert target.status == "ineligible"
    assert target.reasons == [f"stage_not_validation_ready:{stage}"]
    assert all(t.status != "planned" for t in plan.targets)


def test_workspace_mismatch_and_unknown_ids_fail_closed():
    plan = _plan([opp("elsewhere", workspace="other")], requested_ids=["elsewhere", "unknown-id"])
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["elsewhere"].reasons == ["workspace_mismatch"]
    assert by_id["unknown-id"].reasons == ["opportunity_not_found"]
    assert plan.status == "blocked"
    assert "verify_opportunity_id:unknown-id" in plan.next_safe_steps


def test_missing_price_evidence_makes_the_target_partial_and_names_the_gap():
    plan = _plan([opp("no-price", metadata={})])
    target = plan.targets[0]
    assert target.status == "partial"
    assert target.reasons == ["missing_evidence:price_or_cost_evidence"]
    assert target.scorecard_preview["recommendation"] == "request_more_evidence"
    assert "supply_evidence:price_or_cost_evidence:no-price" in plan.next_safe_steps


def test_service_with_missing_inputs_is_skipped_not_guessed(monkeypatch):
    monkeypatch.setattr(runner, "build_validation_service_plan", lambda opportunity: ["product_research", "unit_economics"])
    plan = _plan([opp("skip-me", metadata={"price": 40})])
    target = plan.targets[0]
    assert target.planned_services == ["product_research"]
    assert target.skipped_services == {"unit_economics": ["offer", "product"]}
    assert target.status == "partial"
    assert "supply_inputs:unit_economics:offer,product:skip-me" in plan.next_safe_steps


def test_unsupported_service_is_reviewed_as_a_contract_gap_not_as_missing_evidence(monkeypatch):
    monkeypatch.setattr(runner, "build_validation_service_plan", lambda opportunity: ["product_research", "creative_growth"])
    plan = _plan([opp("odd", metadata={"price": 40})])
    target = plan.targets[0]
    assert "unsupported_service:creative_growth" in target.reasons
    assert "review_service_contract:creative_growth:odd" in plan.next_safe_steps
    assert not any(step.startswith("supply_inputs:creative_growth") for step in plan.next_safe_steps)
    assert not any("missing_evidence:unsupported_service" in reason for reason in target.reasons)


# --- scorecard compatibility -------------------------------------------------------------------------


def test_preview_scorecards_are_existing_scorecard_shaped_and_never_registered():
    plan = _plan([opp("a", 80), opp("b", 70)])
    for target in plan.targets:
        preview = ValidationScorecard.from_dict(target.scorecard_preview)
        assert preview.scorecard_id.startswith("scorecard_preview_")
        assert preview.metadata["preview"] is True
        assert preview.metadata["registered"] is False


def test_preview_never_recommends_launch_without_completed_service_results():
    plan = _plan([opp("a", 80), opp("b", 70), opp("c", 60, metadata={})])
    assert all(t.scorecard_preview["transition_recommendation"] != "launch_candidate" for t in plan.targets)
    assert all(t.scorecard_preview["passed_checks"] == [] for t in plan.targets)


def test_existing_scorecard_builder_keeps_its_default_identifier_contract():
    scorecard = build_validation_scorecard(opp("plain"), [])
    assert scorecard.scorecard_id.startswith("scorecard_")
    assert not scorecard.scorecard_id.startswith("scorecard_preview_")


# --- safety and non-authorization --------------------------------------------------------------------


def test_safety_block_and_handoff_are_non_authorizing():
    plan = _plan([opp("a", 80)])
    assert plan.safety["planning_only"] is True
    assert plan.safety["read_only"] is True
    assert plan.safety["execution_authorized"] is False
    assert plan.safety["network_calls"] is False
    assert plan.safety["provider_calls"] is False
    assert plan.safety["external_mutations"] is False
    assert plan.safety["approval_authority"].startswith("CompanyOS Approval Ledger")
    assert plan.safety["trustos_gate"] == "not_evaluated_by_plan"
    assert plan.safety["workspace_isolation_gate"] == "not_evaluated_by_plan"
    assert plan.safety["launch_authority"] == "none"
    handoff = plan.execution_handoff
    assert handoff["authorized"] is False
    assert handoff["requires_explicit_invocation"] is True
    assert handoff["payload"]["apply_transitions"] is False
    assert "service executor invocations" in handoff["side_effects_disclosed"]


def test_no_approval_is_ever_granted_by_the_plan():
    plan = _plan([opp("g-1", 90), opp("g-2", 80), opp("g-3", 70)], budgets=[_budget(soft=5.0)])
    serialized = json.dumps(plan.to_dict(), sort_keys=True)
    assert '"approved"' not in serialized
    assert plan.safety["execution_authorized"] is False


def test_raw_metadata_values_are_never_echoed_into_the_plan():
    plan = _plan([opp("secret", metadata={**FULL_METADATA, "api_token": CANARY})])
    assert CANARY not in json.dumps(plan.to_dict(), sort_keys=True, default=str)


def test_planned_services_match_the_existing_service_plan_contract():
    plan = _plan([opp("contract", 80)])
    assert plan.targets[0].planned_services == PLANNED_SERVICES
    assert "creative_growth" not in plan.targets[0].planned_services


def test_warnings_are_part_of_the_plan_and_its_identity():
    plain = _plan([opp("w", 80)])
    flagged = _plan([opp("w", 80)], warnings=["evidence_pool_may_be_truncated"])
    assert flagged.warnings == ["evidence_pool_may_be_truncated"]
    assert plain.plan_id != flagged.plan_id


# --- third-review hardening -------------------------------------------------------------------------


def test_learning_context_rejects_unknown_keys_so_misspellings_cannot_drop_constraints():
    with pytest.raises(ValueError):
        _plan([opp("opp-a")], learning_context={"learning_events": learning_context()["events"]})


@pytest.mark.parametrize("missing", ["candidate_id", "action_taken"])
def test_learning_events_must_name_their_candidate_and_action(missing):
    event = {**learning_context()["events"][0]}
    event.pop(missing)
    with pytest.raises(ValueError):
        _plan([opp("candidate-a")], learning_context={"events": [event]})


def test_other_workspace_opportunity_does_not_echo_its_name_or_stage():
    other = opp("elsewhere", workspace="client-b", name="Confidential Pricing Play", stage="validation_ready")
    plan = _plan([other], requested_ids=["elsewhere"])
    target = plan.targets[0]
    assert target.reasons == ["workspace_mismatch"]
    assert target.name == "" and target.stage == ""
    assert "Confidential" not in json.dumps(plan.to_dict(), sort_keys=True)


def test_non_string_evidence_ids_fail_closed_without_aborting_the_plan():
    plan = _plan([opp("int-ev", evidence=(5,)), opp("ok", 70)], evidence_records=[Evidence("5"), Evidence("ev-1")])
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["int-ev"].eligible is True
    assert by_id["ok"].eligible is True


def test_truncated_pool_reports_reference_outside_the_loaded_pool_not_an_unresolved_reference():
    plan = _plan([opp("late", evidence=("ev-late",))], evidence_records=POOL, warnings=["evidence_pool_may_be_truncated"])
    target = plan.targets[0]
    assert target.reasons == ["evidence_reference_outside_loaded_pool:ev-late"]
    assert "reload_complete_evidence_pool:late" in plan.next_safe_steps
    assert not any(step.startswith("resolve_evidence_reference") for step in plan.next_safe_steps)


def test_one_record_listed_twice_is_one_target_but_separate_records_for_one_id_fail_closed():
    record = opp("twin", 80)
    assert [t.status for t in _plan([record, record]).targets] == ["planned"]
    for copy in (opp("twin", 80), opp("twin", 50, stage="discovered"), replace(record)):
        assert _plan([record, copy]).targets[0].reasons == ["duplicate_opportunity_records"]


def test_preview_reports_no_planned_service_as_a_failed_check():
    plan = _plan([opp("clean", 80)])
    preview = plan.targets[0].scorecard_preview
    assert not any(item.endswith("_planned") or item.endswith("_blocked") or item.endswith("_skipped") for item in preview["failed_checks"])
    assert preview["metadata"]["preflight_only"] is True


def test_plan_identity_binds_the_full_learning_event_content():
    base = learning_context()
    tweaked = json.loads(json.dumps(base))
    tweaked["events"][0]["confidence"] = 0.1
    assert _plan([opp("candidate-a")], learning_context=base).plan_id != _plan([opp("candidate-a")], learning_context=tweaked).plan_id


def test_execution_handoff_does_not_carry_the_planning_objective_into_the_run():
    plan = _plan([opp("ready", 80)])
    payload = plan.execution_handoff["payload"]
    assert "objective" not in payload
    assert payload["apply_transitions"] is False


def test_evidence_gap_steps_are_emitted_for_every_eligible_target_not_only_partial_ones():
    budget = _budget(soft=0.0, hard=20.0, limit=20.0, approval=10.0)
    plan = _plan([opp("gap", 80, metadata={"price": 40, "product": {"sku": "x"}, "offer": {"price": 1}, "retail_price": 40}), opp("price-gap", 70, metadata={})], budgets=[budget])
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["price-gap"].eligible is True
    assert "supply_evidence:price_or_cost_evidence:price-gap" in plan.next_safe_steps


# --- fourth-review hardening -------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["workspace_id", "outcome", "event_type", "learning_event_id"])
def test_learning_events_must_name_their_workspace_outcome_and_type(key):
    event = {**learning_context()["events"][0]}
    event.pop(key)
    with pytest.raises(ValueError):
        _plan([opp("candidate-a")], learning_context={"events": [event]})


def test_misspelled_outcome_fails_closed_instead_of_becoming_inconclusive():
    event = {**learning_context()["events"][0], "outcome": "killled"}
    with pytest.raises(ValueError):
        _plan([opp("candidate-a")], learning_context={"events": [event]})


def test_learning_constraints_stay_scoped_to_their_workspace():
    event = {**learning_context()["events"][0], "workspace_id": "other-workspace"}
    plan = _plan([opp("candidate-a", 80)], learning_context={"events": [event]})
    target = plan.targets[0]
    assert target.status == "planned"
    assert target.learning["kill_blocks_resumption"] is False


def test_requested_opportunities_beyond_the_limit_are_reported_not_dropped():
    candidates = [opp(f"r-{i}", 90 - i) for i in range(6)]
    plan = _plan(candidates, requested_ids=[f"r-{i}" for i in range(6)], limit=5)
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["r-5"].reasons == ["beyond_limit"]
    assert by_id["r-5"].status == "ineligible"
    assert plan.status == "partial"
    assert "raise_limit_or_split_request:r-5" in plan.next_safe_steps


def test_unrequested_candidates_beyond_the_limit_are_counted_in_warnings():
    candidates = [opp(f"u-{i}", 90 - i) for i in range(6)]
    plan = _plan(candidates, limit=4)
    assert plan.warnings == ["validation_ready_beyond_limit:2"]
    assert len(plan.targets) == 4


def test_preview_governor_status_matches_the_final_target_status():
    plan = _plan([opp("priceless", 80, metadata={})])
    target = plan.targets[0]
    assert target.status == "partial"
    assert target.scorecard_preview["metadata"]["governor_status"] == "partial"


def test_budgets_supplied_as_a_generator_behave_like_a_list():
    budget = _budget(soft=5.0)
    from_list = _plan([opp("g-1", 90), opp("g-2", 80), opp("g-3", 70)], budgets=[budget])
    from_generator = _plan([opp("g-1", 90), opp("g-2", 80), opp("g-3", 70)], budgets=(item for item in [budget]))
    assert from_generator.to_dict() == from_list.to_dict()


# --- fifth-review hardening -------------------------------------------------------------------------


def _trustos_hold_events(candidate):
    return {"events": [{"learning_event_id": f"trust-{i}", "event_type": "trustos_review", "outcome": "blocked", "action_taken": "deep_validate_product", "candidate_id": candidate, "workspace_id": "default", "failure_reasons": ["trust_blocker"]} for i in range(2)]}


def test_trustos_recurrence_is_not_released_by_learning_acknowledgement():
    plan = _plan([opp("candidate-a", 80)], learning_context=_trustos_hold_events("candidate-a"), acknowledged_learning_for=["candidate-a"])
    target = plan.targets[0]
    assert target.status == "blocked"
    assert target.reasons == ["trustos_recurrence_requires_trustos_review"]
    assert target.learning["trustos_hold"] is True
    assert "request_trustos_review:candidate-a" in plan.next_safe_steps


def test_learning_history_beyond_the_ledger_review_bound_blocks_even_when_it_holds_a_kill():
    events = [{"learning_event_id": f"history-{i}", "event_type": "product_validation", "outcome": "inconclusive", "action_taken": "deep_validate_product", "candidate_id": "candidate-a", "workspace_id": "default"} for i in range(25)]
    events.append({"learning_event_id": "history-kill", "event_type": "product_validation", "outcome": "killed", "action_taken": "deep_validate_product", "candidate_id": "candidate-a", "workspace_id": "default", "failure_reasons": ["poor_margin"]})
    target = _plan([opp("candidate-a", 80)], learning_context={"events": events}).targets[0]
    assert target.status == "blocked"
    assert "learning_history_exceeds_review_bound" in target.reasons
    assert target.learning["learning_history_count"] == 26


def test_budget_approval_threshold_becomes_an_explicit_approval_not_a_silent_plan():
    # A low threshold makes the second candidate's projection cross it whether a candidate plans three or four services.
    plan = _plan([opp("d-0", 90), opp("d-1", 80)], budgets=[_budget(soft=15.0, hard=20.0, limit=20.0, approval=5.0)])
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["d-0"].status == "planned"
    assert by_id["d-1"].status == "awaiting_approval"
    assert by_id["d-1"].reasons == ["projected budget use exceeds the approval threshold; finance review required"]
    threshold_rows = [row for row in plan.approvals_required if row["approval_type"] == "budget_approval_threshold"]
    assert [row["opportunity_id"] for row in threshold_rows] == ["d-1"]
    assert threshold_rows[0]["approver_role"] == "finance_manager"
    assert plan.execution_handoff["requires_human_approval"] is True


def test_non_string_opportunity_ids_still_match_learning_and_acknowledgement():
    record = Opportunity(7, "default", "product_hypothesis", "Numbered", "Desk", stage="validation_ready", score=80.0, confidence=0.8, evidence_ids=["ev-1"], metadata=dict(FULL_METADATA))
    events = {"events": [{"learning_event_id": "numbered-kill", "event_type": "product_validation", "outcome": "killed", "action_taken": "deep_validate_product", "candidate_id": "7", "workspace_id": "default", "failure_reasons": ["poor_margin"]}]}
    blocked = _plan([record], learning_context=events)
    assert blocked.targets[0].status == "blocked"
    released = _plan([record], learning_context=events, acknowledged_learning_for=[7])
    assert released.targets[0].status == "planned"


# --- sixth-review hardening -------------------------------------------------------------------------


def test_misspelled_governor_action_fails_closed_instead_of_dropping_the_constraint():
    event = {**learning_context()["events"][0], "action_taken": "deep_validate_produt"}
    with pytest.raises(ValueError):
        _plan([opp("candidate-a")], learning_context={"events": [event]})


def test_singular_misspelled_reason_key_fails_closed():
    event = {**learning_context()["events"][0]}
    event["failure_reason"] = event.pop("failure_reasons")
    with pytest.raises(ValueError):
        _plan([opp("candidate-a")], learning_context={"events": [event]})


def test_unknown_failure_reason_code_fails_closed():
    event = {**learning_context()["events"][0], "failure_reasons": ["poor_margn"]}
    with pytest.raises(ValueError):
        _plan([opp("candidate-a")], learning_context={"events": [event]})


def test_a_held_candidate_does_not_consume_shared_quota():
    history = [{"learning_event_id": f"held-{i}", "event_type": "product_validation", "outcome": "inconclusive", "action_taken": "deep_validate_product", "candidate_id": "held", "workspace_id": "default"} for i in range(26)]
    candidates = [opp("held", 95)] + [opp(f"ok-{i}", 80 - i) for i in range(5)]
    plan = _plan(candidates, learning_context={"events": history}, budgets=[_budget(soft=100.0, hard=100.0, limit=100.0, approval=100.0)])
    statuses = {t.opportunity_id: t.status for t in plan.targets}
    assert statuses["held"] == "blocked"
    assert [statuses[f"ok-{i}"] for i in range(5)] == ["planned"] * 5
    assert plan.governor_summary["consumed_actions"] == 5


def test_conflicting_evidence_records_for_one_id_fail_closed_in_either_order():
    synthetic = Evidence("ev-1", provenance={"not_real_market_data": True})
    real = Evidence("ev-1", provenance={})
    forward = _plan([opp("cited", 80)], evidence_records=[synthetic, real])
    reverse = _plan([opp("cited", 80)], evidence_records=[real, synthetic])
    assert forward.to_dict() == reverse.to_dict()
    assert forward.targets[0].reasons == ["duplicate_evidence_records:ev-1"]
    assert forward.targets[0].eligible is False


def test_a_candidate_whose_services_are_all_unsupported_reports_the_contract_gap(monkeypatch):
    monkeypatch.setattr(runner, "build_validation_service_plan", lambda opportunity: ["creative_growth"])
    plan = _plan([opp("odd-only", 80)])
    target = plan.targets[0]
    assert target.eligible is False
    assert target.reasons == ["unsupported_service:creative_growth"]
    assert "review_service_contract:creative_growth:odd-only" in plan.next_safe_steps
    assert not any(step.startswith("supply_service_inputs") for step in plan.next_safe_steps)


def test_requested_ids_that_do_not_exist_are_not_reported_as_beyond_the_limit():
    plan = _plan([opp("cand-c", 80)], requested_ids=["cand-c", "ghost"], limit=1)
    by_id = {t.opportunity_id: t for t in plan.targets}
    assert by_id["ghost"].reasons == ["opportunity_not_found"]
    assert by_id["cand-c"].status == "planned"


def test_governor_overlays_are_named_so_the_plan_visibly_overrides_the_governor():
    budget = _budget(soft=15.0, hard=20.0, limit=20.0, approval=5.0)
    plan = _plan([opp("ov-0", 90), opp("ov-1", 80)], budgets=[budget])
    overlaid = next(t for t in plan.targets if t.opportunity_id == "ov-1")
    assert "budget_approval_threshold" in overlaid.governor["plan_overlays"]
    trusted = _plan([opp("ov-t", 80)], learning_context=_trustos_hold_events("ov-t"))
    assert "trustos_hold" in trusted.targets[0].governor["plan_overlays"]
