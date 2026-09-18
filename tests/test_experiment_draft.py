from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from evaluation.commerce.experiment_draft import (
    ExperimentDraftError,
    build_experiment_draft,
    client_safe_report,
    reset_registry,
    simulate_experiment_draft,
)
from evaluation.commerce.experiment_draft_scenarios import run_scenarios, scenario_payloads


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    reset_registry()


def _base(**overrides):
    payload = dict(scenario_payloads()["hydroponics_content_paid_social"])
    payload.update(overrides)
    return payload


def test_happy_path_simulation_never_allows_live() -> None:
    draft = build_experiment_draft(_base())
    sim = simulate_experiment_draft(draft)
    assert draft.live_action_allowed is False
    assert sim.live_action_allowed is False
    assert sim.classification == "simulated_hold"
    assert draft.replay_hash
    report = client_safe_report(draft, sim)
    assert report["live_action_allowed"] is False
    assert "formula" not in report


def test_scenarios_cover_required_lanes_and_models() -> None:
    records = {item["scenario"]: item for item in run_scenarios()}
    assert "hydroponics_content_paid_social" in records
    assert "smart_pet_support_risk" in records
    assert "solar_4g_compliance_block" in records
    assert "commodity_electronics_rejected" in records
    assert "service_client_cro_insufficient" in records
    assert "affiliate_referral_separate" in records
    assert "marketplace_fees_returns" in records
    assert records["mxn_lane"]["currency"] == "MXN"
    assert records["usd_lane"]["currency"] == "USD"
    assert all(item["live_action_allowed"] is False for item in records.values())


@pytest.mark.parametrize(
    "override,reason",
    [
        ({"product_id": ""}, "missing_product_id"),
        ({"offer_id": ""}, "missing_offer_id"),
        ({"supplier_offer_id": ""}, "missing_supplier_offer"),
        ({"channel": "tiktok_ads_live"}, "unsupported_channel"),
        ({"market_lane": ""}, "missing_market_lane"),
        ({"budget_cap": ""}, "missing_budget_cap"),
        ({"stop_condition": ""}, "missing_stop_condition"),
        ({"budget_currency": "USD", "market_lane": "MX-MXN", "planning": {"currency": "MXN", "contribution_after_cac": "1", "evidence_state": "fixture", "assumptions": ()}}, "mixed_currency"),
        ({"promote_evidence_to_live": True}, "fixture_promoted_to_live"),
        ({"launch_authorized": True}, "launch_authorized_input"),
        ({"creative_text": "<script>alert(1)</script>"}, "raw_html"),
        ({"hypothesis": "This feeder cures anxiety in pets"}, "unsupported_medical_health_claim"),
        ({"governor_budget_cap": "10", "budget_cap": "150"}, "budget_exceeds_governor_cap"),
        ({"referenced_workspace_id": "ws-other"}, "cross_workspace_reference"),
        ({"planning": {"currency": "USD", "contribution_after_cac": "-4", "evidence_state": "fixture", "assumptions": ()}}, "negative_downside_contribution"),
    ],
)
def test_negative_classifications(override: dict, reason: str) -> None:
    if reason == "negative_downside_contribution":
        with pytest.raises(ExperimentDraftError, match="negative_downside_contribution"):
            build_experiment_draft(_base(**override))
        return
    draft = build_experiment_draft(_base(**override))
    assert reason in draft.blocked_reasons
    assert draft.live_action_allowed is False


def test_secret_shaped_rejected() -> None:
    with pytest.raises(ExperimentDraftError, match="secret_shaped"):
        build_experiment_draft(_base(api_key="sk_test_not_real"))


def test_duplicate_experiment_id() -> None:
    build_experiment_draft(_base())
    again = build_experiment_draft(_base())
    assert "duplicate_experiment_id" in again.blocked_reasons


def test_replay_stable_and_mutation_detected() -> None:
    first = build_experiment_draft(_base())
    reset_registry()
    second = build_experiment_draft(_base())
    assert first.replay_hash == second.replay_hash
    reset_registry()
    mutated = build_experiment_draft(_base(hypothesis="Changed hypothesis for replay check"))
    assert mutated.replay_hash != first.replay_hash


def test_approval_absent_blocks_clean_simulation_label() -> None:
    draft = build_experiment_draft(_base(approval_state="not_requested"))
    sim = simulate_experiment_draft(draft)
    assert "approval_absent_for_simulation" in sim.blocked_reasons
    assert sim.live_action_allowed is False


def test_live_state_unavailable() -> None:
    with pytest.raises(ExperimentDraftError, match="live_state_unavailable"):
        build_experiment_draft(_base(lifecycle_state="campaign_published"))


def test_affiliate_not_mixed_into_marketplace_retail() -> None:
    draft = build_experiment_draft(_base(business_model="affiliate", channel="marketplace"))
    assert "affiliate_model_kept_separate_from_retail_channel" in draft.blocked_reasons
