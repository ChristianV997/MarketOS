"""System-level proof that the evaluation framework is replayable and read-only."""
from __future__ import annotations

import json
from pathlib import Path

from backend.contracts.events import Event
from evaluation.commerce import compare_evaluations, evaluation_events, evaluate_input, load_evaluation_input


FIXTURE = Path(__file__).parents[1] / "fixtures" / "commerce_evaluation"


def test_full_evaluation_round_trip_is_deterministic():
    value = load_evaluation_input(FIXTURE)
    first = evaluate_input(value)
    second = evaluate_input(value)

    assert first.to_dict() == second.to_dict()
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    assert first.reproducibility.reproducible is True
    assert first.read_only is True
    assert first.mutated is False


def test_evaluation_events_are_canonical_and_replayable():
    report = evaluate_input(load_evaluation_input(FIXTURE))
    events = evaluation_events(report)

    assert [event.event_type for event in events] == [
        "commerce_evaluation_started",
        "commerce_engine_evaluated",
        "commerce_engine_evaluated",
        "commerce_engine_evaluated",
        "commerce_engine_evaluated",
        "commerce_engine_evaluated",
        "commerce_evaluation_completed",
    ]
    for event in events:
        Event.from_dict(event.to_dict())
        assert event.metadata["dry_run"] is True
        assert event.metadata["read_only"] is True
        assert event.metadata["non_authoritative"] is True
        assert event.metadata["manual_approval_required"] is True
        assert event.metadata["no_launch_authority"] is True
        assert event.metadata["no_spend_authority"] is True


def test_comparison_answers_whether_the_same_run_improved():
    value = load_evaluation_input(FIXTURE)
    baseline = evaluate_input(value)
    current = evaluate_input(value)
    comparison = compare_evaluations(baseline, current)

    assert comparison.ranking_stability == 1.0
    assert comparison.improved_metrics == ()
    assert comparison.worsened_metrics == ()
    assert comparison.unchanged_metrics


def test_empty_input_is_explicitly_insufficient_not_positive():
    report = evaluate_input(load_evaluation_input(FIXTURE / "missing.jsonl"))

    assert report.overall["run_quality"] == "insufficient_evidence"
    assert report.overall["overall_evidence_completeness"] == 0.0
    assert report.reproducibility.reproducible is False
    assert report.read_only is True
    assert report.mutated is False
