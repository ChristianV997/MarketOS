"""Tests for backend.validation.shadow_flag_report — deterministic synthetic
event_store fixtures, not live journal reads (the harness is read-only
reporting; these tests prove the reporting logic itself is correct)."""
import os

import pytest

from backend.orchestration.event_store import EventStore
from backend.validation.shadow_flag_report import (
    FLAG_SPECS,
    generate_flag_report,
    generate_report,
)


@pytest.fixture
def store(tmp_path):
    return EventStore(path=str(tmp_path / "events.jsonl"))


def _spec(flag_name: str):
    return next(s for s in FLAG_SPECS if s.flag_name == flag_name)


def test_numeric_flag_insufficient_data_below_min_samples(store):
    for i in range(5):
        store.append("wf", "shadow_product_bandit_weighting", data={
            "bandit_w_stub": 0.1, "bandit_w_used": 0.2,
        })
    report = generate_flag_report(_spec("PRODUCT_BANDIT_LIVE"), store=store, min_samples=30)
    assert report.overall_recommendation == "insufficient_data"


def test_numeric_flag_recommends_flip_for_clear_consistent_improvement(store):
    for i in range(40):
        store.append("wf", "shadow_product_bandit_weighting", data={
            "bandit_w_stub": 0.10, "bandit_w_used": 0.10 + 0.05 + (0.001 if i % 2 else -0.001),
        })
    report = generate_flag_report(_spec("PRODUCT_BANDIT_LIVE"), store=store, min_samples=30)
    assert report.overall_recommendation == "recommend_flip"
    assert report.metrics[0].significant is True
    assert report.metrics[0].mean_delta > 0


def test_numeric_flag_recommends_against_flip_for_consistent_regression(store):
    for i in range(40):
        store.append("wf", "shadow_product_bandit_weighting", data={
            "bandit_w_stub": 0.10, "bandit_w_used": 0.10 - 0.05 + (0.001 if i % 2 else -0.001),
        })
    report = generate_flag_report(_spec("PRODUCT_BANDIT_LIVE"), store=store, min_samples=30)
    assert report.overall_recommendation == "do_not_flip"


def test_numeric_flag_insufficient_signal_for_noisy_zero_mean_delta(store):
    deltas = [0.05, -0.05, 0.04, -0.04, 0.06, -0.06] * 10
    for d in deltas:
        store.append("wf", "shadow_product_bandit_weighting", data={
            "bandit_w_stub": 0.10, "bandit_w_used": 0.10 + d,
        })
    report = generate_flag_report(_spec("PRODUCT_BANDIT_LIVE"), store=store, min_samples=30)
    assert report.overall_recommendation == "insufficient_signal"
    assert report.metrics[0].significant is False


def test_lower_is_better_metric_flips_delta_sign(store):
    # holdout_uncertainty consistently LOWER than legacy_uncertainty is an
    # improvement — mean_delta should be positive (legacy - holdout > 0).
    for i in range(40):
        store.append("wf", "shadow_calibration_stats", data={
            "legacy_bias": 0.0, "holdout_bias": 0.0,
            "legacy_uncertainty": 0.20, "holdout_uncertainty": 0.10 + (0.001 if i % 2 else -0.001),
        })
    report = generate_flag_report(_spec("CALIBRATION_HOLDOUT_LIVE"), store=store, min_samples=30)
    uncertainty_metric = next(m for m in report.metrics if m.label == "uncertainty")
    assert uncertainty_metric.mean_delta > 0
    assert uncertainty_metric.recommendation == "recommend_flip"


def test_boolean_flag_high_agreement_is_low_risk(store):
    for i in range(40):
        verdict = i % 5 == 0  # varies, but legacy/shadow agree every time
        store.append("wf", "shadow_organic_gate", data={
            "legacy_verdict": verdict, "blended_verdict": verdict,
        })
    report = generate_flag_report(_spec("ORGANIC_GATE_LIVE"), store=store, min_samples=30)
    assert report.agreement_rate == 1.0
    assert report.overall_recommendation == "low_risk_flip"


def test_boolean_flag_low_agreement_needs_review(store):
    for i in range(40):
        store.append("wf", "shadow_organic_gate", data={
            "legacy_verdict": i % 2 == 0, "blended_verdict": i % 3 == 0,
        })
    report = generate_flag_report(_spec("ORGANIC_GATE_LIVE"), store=store, min_samples=30)
    assert report.overall_recommendation == "review_disagreements"


def test_boolean_flag_insufficient_data(store):
    store.append("wf", "shadow_organic_gate", data={"legacy_verdict": True, "blended_verdict": True})
    report = generate_flag_report(_spec("ORGANIC_GATE_LIVE"), store=store, min_samples=30)
    assert report.overall_recommendation == "insufficient_data"


def test_reallocation_flag_reports_magnitude_and_always_requires_human_review(store):
    for i in range(40):
        store.append("wf", "shadow_capital_policy", data={
            "legacy_budgets": [50.0, 50.0],
            "policy": {"budgets": [60.0, 40.0]},
            "total_budget": 100.0,
        })
    report = generate_flag_report(_spec("CAPITAL_POLICY_LIVE"), store=store, min_samples=30)
    assert report.mean_abs_reallocation_frac == pytest.approx(0.1, abs=1e-6)
    assert report.overall_recommendation == "insufficient_signal_requires_human_review"


def test_reallocation_flag_skips_malformed_events(store):
    store.append("wf", "shadow_capital_policy", data={"legacy_budgets": [50.0], "policy": {}, "total_budget": 100.0})
    store.append("wf", "shadow_capital_policy", data={"legacy_budgets": None, "policy": {"budgets": [1.0]}, "total_budget": 100.0})
    report = generate_flag_report(_spec("CAPITAL_POLICY_LIVE"), store=store, min_samples=1)
    assert report.sample_count == 0
    assert report.overall_recommendation == "insufficient_data"


def test_generate_report_covers_all_seven_flags(store):
    report = generate_report(store=store)
    flag_names = {f["flag_name"] for f in report["flags"]}
    assert flag_names == {
        "SCORING_NORMALIZE_LIVE", "PRODUCT_BANDIT_LIVE", "REGIME_CONFIDENCE_WEIGHTING_LIVE",
        "CALIBRATION_HOLDOUT_LIVE", "RISK_ADAPTIVE_LIVE", "ORGANIC_GATE_LIVE", "CAPITAL_POLICY_LIVE",
    }
    assert all(f["overall_recommendation"] == "insufficient_data" for f in report["flags"])


def test_events_of_type_filters_correctly(store):
    store.append("wf1", "shadow_decision_scoring", data={"legacy_score": 1.0, "normalized_score": 1.0})
    store.append("wf2", "shadow_organic_gate", data={"legacy_verdict": True, "blended_verdict": True})
    scoring_events = store.events_of_type("shadow_decision_scoring")
    assert len(scoring_events) == 1
    assert scoring_events[0]["workflow_id"] == "wf1"
