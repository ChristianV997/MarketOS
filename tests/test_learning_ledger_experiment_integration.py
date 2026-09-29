from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evaluation import CampaignCandidate, CampaignObservation, DataQuality, evaluate_campaign
from evaluation.companyos.learning_ledger import (
    build_learning_ledger_report,
    derive_governor_influence,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "learning_ledger"
WORKSPACE_ID = "internal-companyos"
OBSERVED_AT = datetime.now(timezone.utc)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _learning_report(*fixture_names: str):
    context = {"mode": "offline", "workspace_id": WORKSPACE_ID, "events": []}
    for name in fixture_names:
        context["events"].extend(_fixture(name)["events"])
    return build_learning_ledger_report(context=context)


def _campaign_result(product_id: str):
    campaign = CampaignCandidate(
        "campaign-1",
        product_id,
        creative_id="creative-1",
        quality=DataQuality(
            provenance="fixture",
            attribution="attributed",
            observed_at=OBSERVED_AT,
            source_ref="fixture://campaign",
        ),
    )
    observations = [
        CampaignObservation(
            f"observation-{index}",
            campaign.campaign_id,
            product_id=product_id,
            creative_id=campaign.creative_id,
            spend=10,
            revenue=16 + (index % 3),
            conversions=3,
            quality=DataQuality(
                provenance="simulated",
                attribution="attributed",
                observed_at=OBSERVED_AT,
                source_ref="fixture://campaign-observation",
            ),
        )
        for index in range(30)
    ]
    return campaign, observations


def _influence(report, candidate_id: str):
    return derive_governor_influence(
        report,
        action_type="launch_ad_experiment",
        candidate_id=candidate_id,
        workspace_id=WORKSPACE_ID,
        allow_action_type_fallback=False,
    )


def test_loss_advisory_keeps_do_not_repeat_recommendation_and_provenance():
    influence = _influence(
        _learning_report("ad_experiment_loser_fixture.json"),
        "portable-espresso-maker",
    )

    assert influence.do_not_repeat_blocked is True
    assert influence.provenance == ("fixture-ad-loser",)
    assert influence.iteration_recommendation


def test_win_advisory_surfaces_existing_next_iteration_recommendation():
    influence = _influence(
        _learning_report("ad_experiment_winner_fixture.json"),
        "mini-thermal-printer",
    )

    assert influence.provenance == ("fixture-ad-winner",)
    assert influence.iteration_recommendation == (
        "Carry the recorded success reasons into a bounded hypothesis; "
        "no execution authorization is implied."
    )


def test_candidate_scoping_does_not_leak_another_products_loss_rule():
    report = _learning_report(
        "ad_experiment_loser_fixture.json",
        "ad_experiment_winner_fixture.json",
    )

    influence = _influence(report, "mini-thermal-printer")

    assert influence.loss_count == 0
    assert influence.do_not_repeat_blocked is False
    assert influence.provenance == ("fixture-ad-winner",)
    assert influence.iteration_recommendation.startswith("Carry the recorded success")


def test_empty_history_has_no_influence_or_recommendation():
    report = build_learning_ledger_report(context=_fixture("learning_ledger_context.json"))

    influence = _influence(report, "portable-espresso-maker")

    assert influence.evidence_mode == "not_run"
    assert influence.provenance == ()
    assert influence.iteration_recommendation == ""
    assert influence.do_not_repeat_blocked is False
    assert influence.hold_or_avoid is False
    assert influence.trustos_recurrence_blocked is False


def test_repeated_fixture_projection_is_deterministic():
    report = _learning_report(
        "ad_experiment_loser_fixture.json",
        "ad_experiment_winner_fixture.json",
    )

    first = _influence(report, "mini-thermal-printer").to_dict()
    second = _influence(report, "mini-thermal-printer").to_dict()

    assert first == second


def _evaluate_with_report(campaign, observations, report):
    influence = _influence(report, campaign.product_id or campaign.campaign_id)
    try:
        return evaluate_campaign(
            campaign,
            observations,
            learning_influence=influence,
        )
    except TypeError as exc:
        if "unexpected keyword argument 'learning_influence'" in str(exc):
            pytest.fail("campaign readiness currently drops fixture-backed ledger guidance")
        raise


def test_campaign_advisory_rejects_action_wide_fallback_from_another_product():
    campaign, observations = _campaign_result("mini-thermal-printer")
    report = _learning_report("ad_experiment_loser_fixture.json")
    influence = derive_governor_influence(
        report,
        action_type="launch_ad_experiment",
        candidate_id=campaign.product_id,
        workspace_id=WORKSPACE_ID,
    )

    with pytest.raises(ValueError, match="action-wide"):
        evaluate_campaign(campaign, observations, learning_influence=influence)


def test_campaign_advisory_can_fail_closed_when_only_other_candidates_have_history():
    campaign, observations = _campaign_result("mini-thermal-printer")
    report = _learning_report("ad_experiment_loser_fixture.json")
    influence = _influence(report, campaign.product_id)

    result = evaluate_campaign(campaign, observations, learning_influence=influence).to_dict()
    advisory = result["learning_advisory"]["influence"]

    assert advisory["evidence_mode"] == "not_run"
    assert advisory["recency_label"] == "no_matching_event"
    assert advisory["provenance"] == []
    assert advisory["do_not_repeat_blocked"] is False


def test_campaign_report_surfaces_loss_recommendation_with_provenance_without_changing_decisions():
    campaign, observations = _campaign_result("portable-espresso-maker")
    report = _learning_report("ad_experiment_loser_fixture.json")
    baseline = evaluate_campaign(campaign, observations)

    advised = _evaluate_with_report(campaign, observations, report)

    assert advised.experiment == baseline.experiment
    assert advised.launchable == baseline.launchable
    assert advised.reasons == baseline.reasons
    assert "learning_advisory" not in baseline.to_dict()
    advisory = advised.to_dict()["learning_advisory"]
    assert advisory["authority"] == "advisory_only"
    assert advisory["decision_effect"] == "none"
    influence = advisory["influence"]
    assert influence["candidate_id"] == campaign.product_id
    assert influence["do_not_repeat_blocked"] is True
    assert influence["iteration_action_type"] == "generate_creative_batch"
    assert influence["iteration_recommendation"]
    assert influence["iteration_recommendation_source_event_id"] == "fixture-ad-loser"
    assert influence["provenance"] == ["fixture-ad-loser"]


def test_campaign_report_surfaces_win_iteration_guidance_with_provenance():
    campaign, observations = _campaign_result("mini-thermal-printer")
    report = _learning_report("ad_experiment_winner_fixture.json")

    advised = _evaluate_with_report(campaign, observations, report)

    influence = advised.to_dict()["learning_advisory"]["influence"]
    assert influence["candidate_id"] == campaign.product_id
    assert influence["iteration_recommendation"] == (
        "Carry the recorded success reasons into a bounded hypothesis; "
        "no execution authorization is implied."
    )
    assert influence["iteration_recommendation_source_event_id"] == "fixture-ad-winner"
    assert influence["provenance"] == ["fixture-ad-winner"]


def test_campaign_report_with_empty_history_is_explicitly_not_run():
    campaign, observations = _campaign_result("portable-espresso-maker")
    report = build_learning_ledger_report(context=_fixture("learning_ledger_context.json"))

    advised = _evaluate_with_report(campaign, observations, report)

    influence = advised.to_dict()["learning_advisory"]["influence"]
    assert influence["evidence_mode"] == "not_run"
    assert influence["provenance"] == []
    assert influence["iteration_recommendation"] == ""
    assert influence["do_not_repeat_blocked"] is False
    assert influence["hold_or_avoid"] is False
    assert influence["trustos_recurrence_blocked"] is False


def test_campaign_report_with_fixture_history_is_deterministic():
    campaign, observations = _campaign_result("mini-thermal-printer")
    report = _learning_report(
        "ad_experiment_loser_fixture.json",
        "ad_experiment_winner_fixture.json",
    )

    first = _evaluate_with_report(campaign, observations, report).to_dict()
    second = _evaluate_with_report(campaign, observations, report).to_dict()

    assert first == second


def test_campaign_report_remains_backward_compatible_without_ledger_input():
    campaign, observations = _campaign_result("portable-espresso-maker")

    result = evaluate_campaign(campaign, observations).to_dict()

    assert "learning_advisory" not in result
