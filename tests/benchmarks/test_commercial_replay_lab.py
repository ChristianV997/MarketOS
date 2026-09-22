"""tests/benchmarks/test_commercial_replay_lab.py — Test commercial replay laboratory suite.

Validates:
1. Scenario replay laboratory runs all 5 scenarios with replay_equal == True and certifies invariants.
2. Achieved stages strictly match canonical expectations.
3. 7-dimensional sensitivity matrix executes cleanly across all 7 dimensions.
4. Scaling profiler returns valid timings and positive throughput.
5. Statistical comparison with separated warm-up produces 0 hash drift, p50/p95/variance, and scenario metrics.
6. Canonical replay integration verifies all 13 safety invariants when available and conforms to schema.
7. Fail-closed rejection of adversarial authority payloads.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from backend.contracts.events import Event
from evaluation.commerce.dry_run_events import lifecycle_events
from evaluation.commerce.dry_run_lifecycle import run_dry_run_lifecycle
from evaluation.commerce.dry_run_scenarios import hydroponics_positive_candidate
from scripts.benchmarks.benchmark_commercial_replay_lab import (
    EXPECTED_STAGES,
    ScenarioReplayLaboratory,
    SensitivityMatrixLaboratory,
    ScalingAndProfilerLaboratory,
    StatisticalComparisonLaboratory,
)
from scripts.benchmarks.lab_certification import (
    PUBLISHED_COMMERCE_AGGREGATE_HASHES,
    aggregate_replay_hash,
    field_hash_negative_control,
    unavailable_import_must_not_certify,
)


def test_scenario_replay_laboratory_all_five_scenarios():
    records = ScenarioReplayLaboratory.run_scenarios()
    assert len(records) == 5

    for rec in records:
        assert rec.replay_equal is True
        assert rec.first_replay_hash == rec.second_replay_hash
        assert rec.first_replay_hash != ""
        assert rec.event_count == 17
        assert rec.event_scope == "commerce_lifecycle"
        assert rec.evidence_classification in {"observed", "fixture", "assumed"}
        assert rec.evidence_classification != "live_readonly"
        assert len(rec.first_hash_sequence) == 17
        assert rec.first_hash_sequence == rec.second_hash_sequence
        assert rec.aggregate_first_hash == rec.aggregate_second_hash
        assert rec.aggregate_first_hash == PUBLISHED_COMMERCE_AGGREGATE_HASHES[rec.scenario_id]
        assert rec.hash_authority == "Event.replay_hash"
        assert rec.achievable_stage == EXPECTED_STAGES[rec.scenario_id]
        assert rec.live_authority_violations == ()
        assert rec.live_actions_taken is False
        assert rec.sequence_issues == ()
        assert rec.wall_ms > 0
        assert rec.output_bytes > 0

    cert = ScenarioReplayLaboratory.verify_scenario_invariants(records)
    assert cert["all_passed"] is True
    assert cert["scenarios_certified"] == 5
    by_id = {rec.scenario_id: rec for rec in records}
    assert by_id["hydroponics_positive_candidate"].evidence_classification == "observed"
    assert by_id["solar_4g_security_blocked_candidate"].evidence_classification == "fixture"


def test_sensitivity_matrix_laboratory_7d_completeness():
    results = SensitivityMatrixLaboratory.evaluate_7d_matrix()
    expected_dimensions = {
        "cac",
        "supplier_shipping",
        "fx_reserve_rate",
        "return_rate",
        "defect_rate",
        "warranty_rate",
        "delivery_delay_days",
    }
    assert set(results.keys()) == expected_dimensions

    for dim, points in results.items():
        assert len(points) >= 4, f"Dimension {dim} has fewer than 4 evaluation points"
        for pt in points:
            assert pt.dimension == dim
            assert Decimal(pt.net_sales) > Decimal("0")
            assert Decimal(pt.product_cost) > Decimal("0")
            assert Decimal(pt.cash_required_per_order) > Decimal("0")
            assert Decimal(pt.break_even_cac) >= Decimal("0")
            assert Decimal(pt.return_lag_exposure) >= Decimal("0")


def test_scaling_and_profiler_laboratory():
    points = ScalingAndProfilerLaboratory.run_scaling_benchmark([5, 10])
    assert len(points) == 2
    for pt in points:
        assert pt.total_evaluations == pt.dimension_point_count * 7
        assert pt.wall_ms > 0
        assert pt.evals_per_sec > 0
        assert pt.peak_memory_kb > 0
        assert pt.bytes_per_eval > 0


def test_statistical_comparison_laboratory_warmup_and_metrics():
    summary, cycle_times = StatisticalComparisonLaboratory.run_repeated_cycles(iterations=3, warmup_cycles=2)
    assert summary.warmup_cycles == 2
    assert summary.iterations == 3
    assert summary.total_runs == 15
    assert len(cycle_times) == 3
    assert summary.hash_drift_detected is False
    assert summary.mean_cycle_ms > 0
    assert summary.p50_cycle_ms > 0
    assert summary.median_cycle_ms == summary.p50_cycle_ms
    assert summary.min_cycle_ms <= summary.max_cycle_ms
    assert summary.p95_cycle_ms >= summary.p50_cycle_ms
    assert summary.variance_cycle_ms >= 0
    assert len(summary.scenario_metrics) == 5

    for s_name, s_metric in summary.scenario_metrics.items():
        assert s_metric["event_count"] == 17
        assert s_metric["mean_ms"] > 0
        assert s_metric["p50_ms"] > 0
        assert s_metric["min_ms"] <= s_metric["max_ms"]
    assert summary.is_small_sample is True
    assert summary.tail_estimation_method == "sample_maximum_small_n_guard"
    assert summary.p95_cycle_ms == summary.max_cycle_ms
    assert summary.p99_cycle_ms == summary.max_cycle_ms


def test_profiler_generates_entries():
    raw_text, top_entries = ScalingAndProfilerLaboratory.profile_commercial_cycle(runs=2)
    assert len(raw_text) > 0
    assert len(top_entries) > 0
    for entry in top_entries:
        assert "function" in entry
        assert entry["total_calls"] > 0


def test_canonical_replay_integration_does_not_self_certify_commerce_only_cli():
    result = ScenarioReplayLaboratory.run_canonical_replay_integration()
    assert result["authority"] == "scripts.run_commercial_replay_integration"
    assert result["status"] in {
        "available",
        "unmerged_dependency",
        "commerce_only_cli_not_pr279",
        "truncated_or_wrong_scope",
        "unavailable",
    }
    assert unavailable_import_must_not_certify(result["status"], result.get("all_invariants_satisfied"))
    if result["status"] != "available":
        assert result.get("all_invariants_satisfied") is False
        assert result.get("all_replay_equal") is False
        assert all(v is False for v in result["invariant_checks"].values())
        return
    assert result["mode"] == "pr279_concat"
    assert result["all_invariants_satisfied"] is True
    assert result["rows_evaluated"] == 5
    for s_inv in result["scenario_invariants"]:
        assert s_inv["event_count"] == 37
        assert s_inv["event_scope"] == "cli_concat_commerce_plus_fulfillment"


def test_adversarial_authority_fail_closed_rejection():
    res = ScenarioReplayLaboratory.verify_adversarial_authority_rejection()
    assert res["adversarial_events_tested"] == 2
    assert res["fail_closed"] is True
    assert len(res["violations_detected"]) == 2


def test_altered_intermediate_event_replay_hash_changes_aggregate():
    report = run_dry_run_lifecycle(hydroponics_positive_candidate())
    events = lifecycle_events(report, workspace_id="ws-tamper")
    assert len(events) == 17
    original = [event.replay_hash() for event in events]
    mid = events[8]
    tampered = Event(
        mid.event_id,
        mid.workspace_id,
        mid.aggregate_type,
        mid.aggregate_id,
        mid.event_type,
        mid.schema_version,
        mid.occurred_at,
        payload={**mid.payload, "tamper": "altered-intermediate"},
        metadata=dict(mid.metadata),
        source=mid.source,
        correlation_id=mid.correlation_id,
        causation_id=mid.causation_id,
    )
    altered = list(original)
    altered[8] = tampered.replay_hash()
    assert altered[8] != original[8]
    assert aggregate_replay_hash(altered) != aggregate_replay_hash(original)
    field = field_hash_negative_control(mid.payload)
    assert not original[8].startswith("field-hash:")
    assert field != original[8]


def test_wrong_event_counts_fail_scenario_invariants():
    records = ScenarioReplayLaboratory.run_scenarios()
    base = records[0]
    for count in (16, 18, 20, 37):
        poisoned = replace(base, event_count=count, event_scope="commerce_lifecycle")
        cert = ScenarioReplayLaboratory.verify_scenario_invariants([poisoned])
        assert cert["all_passed"] is False
        assert cert["checks"]["all_event_counts_match_scope"] is False


def test_empty_records_do_not_vacuously_pass_invariants():
    cert = ScenarioReplayLaboratory.verify_scenario_invariants([])
    assert cert["all_passed"] is False
    assert cert["scenarios_certified"] == 0
