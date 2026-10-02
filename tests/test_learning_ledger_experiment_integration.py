from __future__ import annotations

from dataclasses import replace
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


def test_end_to_end_source_event_tracing_into_readiness_advisory():
    """Trace a source experiment event through ledger recommendations into the readiness advisory.

    Verifies:
    - Event identity & provenance is retained (source_event_id).
    - Recommendation matches the source event.
    - Advisory is strictly 'advisory_only' with decision effect 'none'.
    - Campaign decision (scores, reasons, launchability) is untouched.
    """
    candidate_id = "custom-test-product"
    event_id = "exp-event-source-42"
    custom_events = [
        {
            "learning_event_id": event_id,
            "event_type": "ad_experiment",
            "outcome": "loss",
            "candidate_id": candidate_id,
            "action_taken": "launch_ad_experiment",
            "failure_reasons": ["low_click_through", "poor_creative_angle"],
            "hypothesis": "Testing alternative hook angle.",
            "metrics": [{"name": "click_through_rate", "value": 0.005, "target": 0.02, "sample_size": 500, "unit": "ratio"}],
            "confidence": 0.85,
            "workspace_id": WORKSPACE_ID,
        }
    ]
    report = build_learning_ledger_report(context={"workspace_id": WORKSPACE_ID, "events": custom_events})
    influence = derive_governor_influence(
        report,
        action_type="launch_ad_experiment",
        candidate_id=candidate_id,
        workspace_id=WORKSPACE_ID,
        allow_action_type_fallback=False,
    )

    campaign, observations = _campaign_result(candidate_id)
    baseline = evaluate_campaign(campaign, observations)
    advised = evaluate_campaign(campaign, observations, learning_influence=influence)

    # Invariance check: advisory cannot alter scores, reasons, or launchability
    assert advised.launchable == baseline.launchable
    assert advised.reasons == baseline.reasons
    assert advised.experiment == baseline.experiment

    # Advisory metadata check
    advisory = advised.to_dict()["learning_advisory"]
    assert advisory["authority"] == "advisory_only"
    assert advisory["decision_effect"] == "none"

    # Lineage & provenance check
    inf_dict = advisory["influence"]
    assert inf_dict["candidate_id"] == candidate_id
    assert inf_dict["provenance"] == [event_id]
    assert inf_dict["iteration_recommendation_source_event_id"] == event_id
    assert inf_dict["iteration_action_type"] == "generate_creative_batch"
    assert "hook or audience" in inf_dict["iteration_recommendation"]
    assert inf_dict["do_not_repeat_blocked"] is True


def test_unlaunchable_campaign_cannot_be_authorized_by_winning_learning_influence():
    """Prove an unlaunchable campaign is NOT authorized by a winning ledger advisory."""
    campaign, _ = _campaign_result("mini-thermal-printer")
    report = _learning_report("ad_experiment_winner_fixture.json")
    influence = _influence(report, campaign.product_id)

    # Unlaunchable campaign with zero observations -> missing_observations
    baseline = evaluate_campaign(campaign, observations=[])
    assert baseline.launchable is False
    assert "missing_observations" in baseline.reasons

    advised = evaluate_campaign(campaign, observations=[], learning_influence=influence)
    assert advised.launchable is False
    assert advised.reasons == baseline.reasons
    assert advised.experiment is None
    assert advised.learning_advisory is not None
    assert advised.to_dict()["learning_advisory"]["decision_effect"] == "none"


def test_campaign_advisory_rejects_candidate_mismatch():
    campaign, observations = _campaign_result("portable-espresso-maker")
    report = _learning_report("ad_experiment_winner_fixture.json")
    influence = _influence(report, "mini-thermal-printer")

    with pytest.raises(ValueError, match="learning_influence candidate does not match campaign product"):
        evaluate_campaign(campaign, observations, learning_influence=influence)


def test_campaign_advisory_rejects_action_type_mismatch():
    campaign, observations = _campaign_result("portable-espresso-maker")
    report = _learning_report("ad_experiment_loser_fixture.json")
    influence = _influence(report, campaign.product_id)
    mismatched_influence = replace(influence, action_type="deep_validate_product")

    with pytest.raises(ValueError, match="learning_influence action does not match campaign experiment"):
        evaluate_campaign(campaign, observations, learning_influence=mismatched_influence)


def test_campaign_advisory_rejects_non_governor_influence_type():
    campaign, observations = _campaign_result("portable-espresso-maker")

    class FakeInfluence:
        action_type = "launch_ad_experiment"
        candidate_id = "portable-espresso-maker"
        recency_label = "direct_candidate_match"
        workspace_id = WORKSPACE_ID
        provenance = ("fixture-fake",)
        iteration_recommendation_source_event_id = "fixture-fake"
        def to_dict(self): return {}

    with pytest.raises(TypeError, match="learning_influence must be a LearningGovernorInfluence"):
        evaluate_campaign(campaign, observations, learning_influence=FakeInfluence())  # type: ignore[arg-type]


def test_campaign_advisory_rejects_tampered_provenance():
    campaign, observations = _campaign_result("portable-espresso-maker")
    report = _learning_report("ad_experiment_loser_fixture.json")
    influence = _influence(report, campaign.product_id)
    tampered = replace(influence, iteration_recommendation_source_event_id="spoofed-event-id")

    with pytest.raises(ValueError, match="learning recommendation source must appear in influence provenance"):
        evaluate_campaign(campaign, observations, learning_influence=tampered)


def test_campaign_product_id_empty_falls_back_to_campaign_id():
    campaign_id = "campaign-direct-id"
    campaign = CampaignCandidate(
        campaign_id,
        "",  # empty product_id
        quality=DataQuality(
            provenance="fixture",
            attribution="attributed",
            observed_at=OBSERVED_AT,
            source_ref="fixture://campaign",
        ),
    )
    observations = [
        CampaignObservation(
            "obs-1",
            campaign_id,
            spend=10,
            revenue=20,
            conversions=2,
            quality=DataQuality(
                provenance="simulated",
                attribution="attributed",
                observed_at=OBSERVED_AT,
                source_ref="fixture://obs",
            ),
        )
    ]
    report = build_learning_ledger_report(context={
        "events": [{
            "learning_event_id": "event-for-campaign-id",
            "event_type": "ad_experiment",
            "outcome": "win",
            "candidate_id": campaign_id,
            "action_taken": "launch_ad_experiment",
            "workspace_id": WORKSPACE_ID,
        }]
    })
    influence = derive_governor_influence(
        report,
        action_type="launch_ad_experiment",
        candidate_id=campaign_id,
        workspace_id=WORKSPACE_ID,
        allow_action_type_fallback=False,
    )

    advised = evaluate_campaign(campaign, observations, learning_influence=influence)
    advisory = advised.to_dict()["learning_advisory"]
    assert advisory["influence"]["candidate_id"] == campaign_id
    assert advisory["influence"]["provenance"] == ["event-for-campaign-id"]


def test_deterministic_replay_under_event_shuffling():
    events = [
        {
            "learning_event_id": f"evt-{i}",
            "event_type": "ad_experiment",
            "outcome": "win" if i % 2 == 0 else "loss",
            "candidate_id": "shuffle-candidate",
            "action_taken": "launch_ad_experiment",
            "failure_reasons": ["poor_offer"] if i % 2 != 0 else [],
            "workspace_id": WORKSPACE_ID,
        }
        for i in range(6)
    ]
    perm1 = events
    perm2 = list(reversed(events))

    report1 = build_learning_ledger_report(context={"workspace_id": WORKSPACE_ID, "events": perm1})
    report2 = build_learning_ledger_report(context={"workspace_id": WORKSPACE_ID, "events": perm2})

    inf1 = derive_governor_influence(report1, action_type="launch_ad_experiment", candidate_id="shuffle-candidate", workspace_id=WORKSPACE_ID, allow_action_type_fallback=False)
    inf2 = derive_governor_influence(report2, action_type="launch_ad_experiment", candidate_id="shuffle-candidate", workspace_id=WORKSPACE_ID, allow_action_type_fallback=False)

    assert inf1.fingerprint == inf2.fingerprint
    assert inf1.to_dict() == inf2.to_dict()

    campaign, observations = _campaign_result("shuffle-candidate")
    advised1 = evaluate_campaign(campaign, observations, learning_influence=inf1)
    advised2 = evaluate_campaign(campaign, observations, learning_influence=inf2)

    assert advised1.to_dict() == advised2.to_dict()
