"""Deterministic dry-run replay harness (MarketOS mission 7, Phase 4).

This harness invokes only EXISTING public builders and the canonical event
repository/replay-certification helpers -- it is not a second workflow
engine. It runs one composed dry-run cycle (opportunity synthesis ->
validation report -> a small event trail representing that cycle) twice with
identical input and proves: canonical JSON equality, event-count stability,
replay-hash stability, stable ordering, idempotent re-append (no duplicate
side effects), and that no step ever touches a live provider.
"""
from __future__ import annotations

import json

from backend.contracts.events import Event
from backend.events.repository import InMemoryEventRepository
from backend.events.replay_certification import hash_sequence, validate_event_sequence
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.product_validation_report import generate as generate_validation_report

CANDIDATE_ID = "replay-widget-01"


def _pillars():
    market = {"evidence_mode": "fixture_demo", "top_candidate_id": CANDIDATE_ID, "candidates": [{"candidate_id": CANDIDATE_ID, "query": "widget", "evidence": [{"marketplace": "amazon", "price": 25.0, "source_confidence": 0.8, "evidence_mode": "fixture"}], "score": {"overall_marketplace_opportunity": 0.8, "saturation_score": 0.2, "recommendation": "validate_supplier_first"}}]}
    supplier = {"evidence_mode": "fixture_demo", "top_candidate_id": CANDIDATE_ID, "candidates": [{"candidate_id": CANDIDATE_ID, "query": "widget", "offers": [{"supplier": "cj", "unit_cost": 5.0, "shipping_cost": 1.5, "evidence_mode": "fixture"}], "score": {"overall_supplier_feasibility": 0.8, "recommendation": "validate_supplier_first", "risk_flags": [], "economics": {"target_sell_price": 25.0, "estimated_landed_cost": 6.5, "gross_margin_percent": 0.5, "profit_per_order_before_ad_spend": 12.0}}}]}
    consumer = {"evidence_mode": "fixture_demo", "top_candidate_id": CANDIDATE_ID, "candidates": [{"candidate_id": CANDIDATE_ID, "query": "widget", "evidence": [{"platform": "tiktok", "hook": "solid value", "evidence_mode": "fixture"}], "score": {"overall_consumer_attention": 0.75, "objection_density": 0.1, "recommended_ad_angles": ["value"], "creative_hooks": [{"hook": "solid value"}], "voice_of_customer": {"pain_points": [], "desired_outcomes": [], "objections": []}, "recommendation": "validate_supplier_first"}}]}
    return market, supplier, consumer


def _run_cycle(repository: InMemoryEventRepository, *, run_tag: str) -> dict:
    """Run one full dry-run cycle through existing public builders and
    record it in the canonical event repository. Timestamps are frozen
    constants (not wall-clock) so two runs of the same scenario are
    byte-for-byte comparable -- this is the harness explicitly classifying
    time as deterministic/simulated rather than letting it silently vary."""
    market, supplier, consumer = _pillars()
    synthesis = build_product_opportunity_synthesis(market, supplier, consumer).to_dict()
    report = generate_validation_report(
        client_name="Replay Harness Client",
        opportunity_synthesis=synthesis,
        marketplace_trends=market,
        supplier_feasibility=supplier,
        consumer_attention=consumer,
    ).to_dict()

    # Record the cycle as two events with a fixed, non-wall-clock timestamp.
    # The event_id is derived from stable inputs (not a random uuid) so a
    # true replay of the same scenario produces the same event_id and is
    # therefore idempotent when appended twice, exactly like re-delivery.
    events = [
        Event(event_id=f"synth-{CANDIDATE_ID}", workspace_id="ws-replay-harness", aggregate_type="dry_run_cycle", aggregate_id=CANDIDATE_ID, event_type="opportunity_synthesized", schema_version=1, occurred_at=1000.0, source="test_harness", payload={"overall_recommendation": synthesis["overall_recommendation"], "combined_opportunity_score": synthesis["combined_opportunity_score"]}),
        Event(event_id=f"valid-{CANDIDATE_ID}", workspace_id="ws-replay-harness", aggregate_type="dry_run_cycle", aggregate_id=CANDIDATE_ID, event_type="validation_report_generated", schema_version=1, occurred_at=1001.0, source="test_harness", payload={"overall_recommendation": report["overall_recommendation"]}),
    ]
    results = repository.append_many(events)
    return {"run_tag": run_tag, "synthesis": synthesis, "report": report, "events": events, "append_results": results}


def test_identical_scenario_produces_byte_identical_canonical_projections():
    repo_a, repo_b = InMemoryEventRepository(), InMemoryEventRepository()
    run_a = _run_cycle(repo_a, run_tag="first")
    run_b = _run_cycle(repo_b, run_tag="second")

    assert json.dumps(run_a["synthesis"], sort_keys=True) == json.dumps(run_b["synthesis"], sort_keys=True)
    assert json.dumps(run_a["report"], sort_keys=True) == json.dumps(run_b["report"], sort_keys=True)

    # Never a live provider: both runs stay flagged read-only/no-network.
    for artifact in (run_a["synthesis"], run_b["synthesis"], run_a["report"], run_b["report"]):
        assert artifact["read_only"] is True and artifact["network_calls"] is False and artifact["mutated"] is False


def test_event_replay_hash_and_count_are_stable_across_independent_runs():
    repo_a, repo_b = InMemoryEventRepository(), InMemoryEventRepository()
    run_a = _run_cycle(repo_a, run_tag="first")
    run_b = _run_cycle(repo_b, run_tag="second")

    assert not validate_event_sequence(run_a["events"])
    assert not validate_event_sequence(run_b["events"])
    assert hash_sequence(run_a["events"]) == hash_sequence(run_b["events"])
    assert [e.event_id for e in repo_a.stream()] == [e.event_id for e in repo_b.stream()]
    assert len(list(repo_a.stream())) == len(list(repo_b.stream())) == 2


def test_replaying_the_same_cycle_twice_is_idempotent_no_duplicate_side_effects():
    repository = InMemoryEventRepository()
    run_1 = _run_cycle(repository, run_tag="first")
    assert all(result.appended for result in run_1["append_results"])
    assert len(list(repository.stream())) == 2

    # Re-deliver the identical cycle (same deterministic event_ids) -- this
    # simulates a retried/re-delivered dry-run replay, not a new one.
    run_2 = _run_cycle(repository, run_tag="replay")
    assert all(not result.appended and result.idempotent for result in run_2["append_results"])
    assert len(list(repository.stream())) == 2, "a replayed cycle must never duplicate events"


def test_replay_produces_a_bounded_sanitized_summary():
    repository = InMemoryEventRepository()
    run = _run_cycle(repository, run_tag="summary")
    summary = {
        "candidate_id": CANDIDATE_ID,
        "overall_recommendation": run["synthesis"]["overall_recommendation"],
        "confidence_grade": run["synthesis"]["confidence_grade"],
        "event_count": len(list(repository.stream())),
        "replay_hash": hash_sequence(run["events"]),
    }
    blob = json.dumps(summary)
    assert len(blob) < 500
    assert "cj" not in blob.lower() and "sk-" not in blob.lower()
