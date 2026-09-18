from evaluation.commerce.dry_run_lifecycle import LIFECYCLE_STEPS, run_dry_run_lifecycle
from evaluation.commerce.dry_run_scenarios import (
    commodity_electronics_rejected_candidate,
    high_ticket_deferred_candidate,
    hydroponics_positive_candidate,
    smart_pet_support_burden_candidate,
    solar_4g_security_blocked_candidate,
)


def test_all_scenarios_report_all_fifteen_steps():
    for builder in (
        hydroponics_positive_candidate,
        smart_pet_support_burden_candidate,
        solar_4g_security_blocked_candidate,
        commodity_electronics_rejected_candidate,
        high_ticket_deferred_candidate,
    ):
        report = run_dry_run_lifecycle(builder())
        assert [step.step for step in report.steps] == list(LIFECYCLE_STEPS)
        assert report.dry_run is True
        assert report.live_actions_taken is False


def test_hydroponics_candidate_clears_every_stage():
    report = run_dry_run_lifecycle(hydroponics_positive_candidate())
    assert report.achievable_stage == "scale_candidate"
    assert report.promoted_to_launch
    assert report.economics.contribution_margin is not None and report.economics.contribution_margin > 0
    assert all(step.status in {"simulated", "draft"} for step in report.steps)


def test_smart_pet_blocked_by_support_ownership():
    report = run_dry_run_lifecycle(smart_pet_support_burden_candidate())
    assert report.achievable_stage == "supplier_validated"
    assert not report.promoted_to_launch
    assert "unknown_support_owner" in report.promotion.blockers
    offer_step = next(step for step in report.steps if step.step == "offer")
    assert offer_step.status == "blocked_upstream"


def test_solar_candidate_blocked_by_compliance_and_evidence_mode():
    report = run_dry_run_lifecycle(solar_4g_security_blocked_candidate())
    assert report.achievable_stage == "economics_screened"
    assert "compliance" in report.promotion.blockers
    assert any(b.startswith("evidence_state_insufficient_for_stage") for b in report.promotion.blockers)


def test_commodity_electronics_rejected_by_competition_and_weak_economics():
    report = run_dry_run_lifecycle(commodity_electronics_rejected_candidate())
    assert report.economics.contribution_margin is not None and report.economics.contribution_margin < 0
    assert "economics" in report.promotion.blockers
    assert "competition" in report.promotion.blockers
    assert report.achievable_stage == "supplier_terms_pending"


def test_high_ticket_deferred_by_missing_reverse_logistics_and_warranty():
    report = run_dry_run_lifecycle(high_ticket_deferred_candidate())
    assert report.achievable_stage == "supplier_validated"
    assert "return_route" in report.promotion.blockers
    assert "warranty_route" in report.promotion.blockers
    assert "unknown_return_owner" in report.promotion.blockers
    assert "unknown_warranty_owner" in report.promotion.blockers


def test_lifecycle_is_deterministic_across_runs():
    first = run_dry_run_lifecycle(smart_pet_support_burden_candidate()).to_dict()
    second = run_dry_run_lifecycle(smart_pet_support_burden_candidate()).to_dict()
    assert first == second


def test_no_scenario_ever_reports_a_live_action():
    for builder in (
        hydroponics_positive_candidate,
        smart_pet_support_burden_candidate,
        solar_4g_security_blocked_candidate,
        commodity_electronics_rejected_candidate,
        high_ticket_deferred_candidate,
    ):
        report = run_dry_run_lifecycle(builder())
        for step in report.steps:
            assert step.status in {"simulated", "draft", "blocked_upstream"}
