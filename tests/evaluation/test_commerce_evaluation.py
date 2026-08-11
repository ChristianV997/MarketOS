"""Deterministic contract and metric tests for Commerce evaluation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.contracts.events import Event
from evaluation.commerce import compare_evaluations, evaluation_events, evaluate_input, load_evaluation_input
from evaluation.commerce.metrics import _confidence_histogram, competition_metrics, supplier_metrics

FIXTURE = Path(__file__).parents[1] / "fixtures" / "commerce_evaluation"


def _fixture_input():
    return load_evaluation_input(FIXTURE)


def test_fixture_evaluation_covers_all_phase1_engines():
    report = evaluate_input(_fixture_input())
    assert tuple(report.to_dict()["engines"]) == (
        "supplier_evidence", "competition_intelligence", "opportunity_scoring", "research_portfolio", "margin_intelligence"
    )
    assert report.overall["event_count"] == 8


def test_evaluation_is_byte_deterministic():
    first = evaluate_input(_fixture_input()).to_dict()
    second = evaluate_input(_fixture_input()).to_dict()
    assert json.dumps(first, sort_keys=True, separators=(",", ":")) == json.dumps(second, sort_keys=True, separators=(",", ":"))


def test_report_has_no_mutation_authority():
    report = evaluate_input(_fixture_input()).to_dict()
    assert report["read_only"] is True
    assert report["mutated"] is False


def test_replay_hash_digest_is_available_and_stable():
    reproducibility = evaluate_input(_fixture_input()).reproducibility
    assert reproducibility.replay_hash_available is True
    assert len(reproducibility.replay_hash_digest) == 64
    assert reproducibility.reproducible is True


def test_supplier_metrics_include_js_and_provenance():
    metrics = evaluate_input(_fixture_input()).to_dict()["engines"]["supplier_evidence"]["metrics"]
    assert metrics["js_rendered"] == 1
    assert metrics["provenance_distribution"]["observed"] > 0
    assert metrics["field_observation_rate"] > 0


def test_competition_metrics_include_spread_and_variance():
    metrics = evaluate_input(_fixture_input()).to_dict()["engines"]["competition_intelligence"]["metrics"]
    assert metrics["observed_competitor_count"] == 2
    assert metrics["market_spread"] == 5.0
    assert metrics["pricing_variance"] == 6.25


def test_opportunity_metrics_include_confidence_buckets():
    metrics = evaluate_input(_fixture_input()).to_dict()["engines"]["opportunity_scoring"]["metrics"]
    assert metrics["high_confidence_count"] == 1
    assert metrics["low_confidence_count"] == 1
    assert metrics["ranking"] == ["candidate-1", "candidate-2"]


def test_research_metrics_include_canonicalization_and_movement():
    metrics = evaluate_input(_fixture_input()).to_dict()["engines"]["research_portfolio"]["metrics"]
    assert metrics["cluster_quality"] == 0.8
    assert metrics["canonicalization_rate"] == 0.5


def test_margin_metrics_expose_observed_provenance():
    metrics = evaluate_input(_fixture_input()).to_dict()["engines"]["margin_intelligence"]["metrics"]
    assert metrics["observed_margin_confidence"] == 0.7
    assert metrics["provenance"] == {"market_price": "observed", "supplier_cost": "observed"}


def test_evaluation_events_are_canonical_and_read_only():
    report = evaluate_input(_fixture_input())
    events = evaluation_events(report)
    assert len(events) == 7
    for event in events:
        Event.from_dict(event.to_dict())
        assert event.metadata["read_only"] is True
        assert event.metadata["non_authoritative"] is True
        assert event.metadata["no_launch_authority"] is True
        assert event.metadata["no_spend_authority"] is True


def test_empty_input_is_explicitly_insufficient():
    report = evaluate_input(load_evaluation_input(FIXTURE / "missing.jsonl"))
    assert report.overall["run_quality"] == "insufficient_evidence"
    assert "evaluation_input_not_found" in report.warnings


def test_comparison_reports_improvement():
    baseline = evaluate_input(_fixture_input())
    current = evaluate_input(_fixture_input())
    comparison = compare_evaluations(baseline, current)
    assert comparison.deltas["overall.overall_confidence"] == 0.0
    assert comparison.ranking_stability == 1.0
    assert comparison.unchanged_metrics


@pytest.mark.parametrize("confidence", [index / 100 for index in range(101)])
def test_confidence_histogram_assigns_every_finite_boundary(confidence):
    histogram = _confidence_histogram([confidence])
    assert sum(histogram.values()) == 1


@pytest.mark.parametrize("field_name", [
    "title", "price", "sku", "category", "variants", "weight_kg", "inventory_status", "warehouse_origin",
    "shipping_cost", "estimated_delivery_days", "quality_evidence", "rating", "reviews_count", "images", "description",
])
def test_supplier_field_statuses_are_counted(field_name):
    record = {"field_status": {field_name: "observed"}, "confidence": 0.5, "extraction_method": "static"}
    metrics, _, _ = supplier_metrics({"supplier_evidence": {"result": record}}, [])
    assert metrics["observed_fields"][field_name] == 1


@pytest.mark.parametrize("status", ["observed", "derived", "assumed", "unavailable", "malformed", "stale", "conflicting"])
def test_supplier_provenance_distribution_preserves_status(status):
    record = {"field_status": {"price": status}, "confidence": 0.2}
    metrics, _, _ = supplier_metrics({"supplier_evidence": {"result": record}}, [])
    assert metrics["provenance_distribution"][status] >= 1


@pytest.mark.parametrize("prices", [[], [10.0], [10.0, 10.0], [10.0, 20.0], [1.0, 2.0, 9.0], [0.0, 100.0]])
def test_competition_pricing_metrics_are_defined_without_inference(prices):
    offers = [{"external_listing_id": str(index), "price": price, "field_status": {"price": "observed"}} for index, price in enumerate(prices)]
    metrics, _, _ = competition_metrics({"competition_evidence": {"offers": offers}}, [])
    assert metrics["offer_count"] == len(prices)
    assert metrics["observed_competitor_count"] == len(prices)
    if len(prices) < 2:
        assert metrics["pricing_variance"] is None
