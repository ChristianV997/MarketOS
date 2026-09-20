"""tests/benchmarks/test_commercial_replay_lab.py — Test commercial replay laboratory suite.

Validates:
1. Scenario replay laboratory runs all 5 scenarios with replay_equal == True and certifies invariants.
2. Achieved stages strictly match canonical expectations.
3. 7-dimensional sensitivity matrix executes cleanly across all 7 dimensions.
4. Scaling profiler returns valid timings and positive throughput.
5. Statistical comparison with separated warm-up produces 0 hash drift, p50/p95/variance, and scenario metrics.
6. Canonical replay integration does not certify #279 invariants when the CLI is unmerged.
7. Fail-closed rejection of adversarial authority payloads and lab negative controls.
8. Commerce lifecycle is 17 events; 37 is #279 CLI concat only.
"""
from __future__ import annotations

from decimal import Decimal

from scripts.benchmarks.benchmark_commercial_replay_lab import (
    CLI_CONCAT_EVENT_COUNT,
    COMMERCE_LIFECYCLE_EVENT_COUNT,
    EXPECTED_STAGES,
    ScenarioReplayLaboratory,
    SensitivityMatrixLaboratory,
    ScalingAndProfilerLaboratory,
    StatisticalComparisonLaboratory,
    aggregate_replay_hash,
    classify_event_scope,
    field_hash_negative_control,
)


def test_scenario_replay_laboratory_all_five_scenarios():
    records = ScenarioReplayLaboratory.run_scenarios()
    assert len(records) == 5

    for rec in records:
        assert rec.replay_equal is True
        assert rec.first_replay_hash == rec.second_replay_hash
        assert rec.first_replay_hash != ""
        assert rec.event_count == COMMERCE_LIFECYCLE_EVENT_COUNT
        assert rec.event_scope == "commerce_lifecycle"
        assert rec.achievable_stage == EXPECTED_STAGES[rec.scenario_id]
        assert rec.live_authority_violations == ()
        assert rec.live_actions_taken is False
        assert rec.sequence_issues == ()
        assert rec.wall_ms > 0
        assert rec.output_bytes > 0
        assert len(rec.hash_sequence) == COMMERCE_LIFECYCLE_EVENT_COUNT
        assert rec.aggregate_replay_hash == aggregate_replay_hash(list(rec.hash_sequence))
        assert len(rec.event_ids) == COMMERCE_LIFECYCLE_EVENT_COUNT
        assert rec.event_ids[0].endswith(":started")
        assert rec.event_ids[-1].endswith(":completed")
        assert rec.evidence_classification in {"observed", "fixture", "assumed", "unknown"}
        assert rec.evidence_classification != "live_readonly"

    cert = ScenarioReplayLaboratory.verify_scenario_invariants(records)
    assert cert["all_passed"] is True
    assert cert["scenarios_certified"] == 5
    assert cert["cli_concat_not_measured_here"] is True


def test_seventeen_versus_thirty_seven_scopes_are_not_like_for_like():
    assert COMMERCE_LIFECYCLE_EVENT_COUNT == 17
    assert CLI_CONCAT_EVENT_COUNT == 37
    assert classify_event_scope(17) == "commerce_lifecycle"
    assert classify_event_scope(37) == "cli_concat_commerce_plus_fulfillment"
    assert classify_event_scope(16) == "unexpected"
    assert classify_event_scope(0) == "unexpected"


def test_synthetic_field_hash_is_negative_control():
    control = field_hash_negative_control({"event_id": "x", "payload": {"a": 1}})
    assert control.startswith("field-hash:")
    records = ScenarioReplayLaboratory.run_scenarios()
    for rec in records:
        assert rec.aggregate_replay_hash != control
        assert rec.first_replay_hash != control
        assert not rec.first_replay_hash.startswith("field-hash:")


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


def test_profiler_generates_entries():
    raw_text, top_entries = ScalingAndProfilerLaboratory.profile_commercial_cycle(runs=2)
    assert len(raw_text) > 0
    assert len(top_entries) > 0
    for entry in top_entries:
        assert "function" in entry
        assert entry["total_calls"] > 0


def test_canonical_replay_integration_safe_invocation():
    result = ScenarioReplayLaboratory.run_canonical_replay_integration()
    assert result["status"] in {"available", "unmerged_dependency"}
    assert result["authority"] == "scripts.run_commercial_replay_integration"
    assert "invariant_checks" in result

    expected_invariants = {
        "all_event_ids_identical",
        "all_ordering_identical",
        "monotonic_timestamps",
        "all_hash_sequences_identical",
        "all_replay_hashes_identical",
        "no_sequence_violations",
        "no_live_authority_violations",
        "live_actions_taken_false",
        "live_attestation_false",
        "governor_simulated",
        "approval_ledger_simulated",
        "trustos_export_sanitized",
        "no_mutations",
    }
    assert set(result["invariant_checks"].keys()) == expected_invariants

    if result["status"] == "unmerged_dependency":
        assert result["all_invariants_satisfied"] is False
        assert result["certification_state"] == "not_executed"
        assert result["rows_evaluated"] == 0
        return

    assert result["result"] == "actual"
    assert result["rows_evaluated"] == 5
    assert result["all_replay_equal"] is True
    assert result["all_launch_blocked"] is True
    assert len(result["scenario_invariants"]) == 5
    if result.get("mode") == "pr279_consolidated":
        assert result["all_invariants_satisfied"] is True
        counts = {row["event_count"] for row in result["scenario_invariants"]}
        assert counts == {CLI_CONCAT_EVENT_COUNT}
    else:
        assert result["all_invariants_satisfied"] is False
        assert result.get("certification_state") == "commerce_subset"


def test_adversarial_authority_fail_closed_rejection():
    res = ScenarioReplayLaboratory.verify_adversarial_authority_rejection()
    assert res["adversarial_events_tested"] == 2
    assert res["fail_closed"] is True
    assert len(res["violations_detected"]) == 2


def test_adversarial_lab_negative_controls():
    res = ScenarioReplayLaboratory.verify_adversarial_lab_failures()
    assert res["all_passed"] is True
    assert res["cases"]["wrong_event_count"] is True
    assert res["cases"]["synthetic_identity_rejected"] is True
    assert res["cases"]["invalid_sample_shape"] is True
    assert res["cases"]["evidence_escalation_denied"] is True
    assert res["cases"]["truncated_symbol"] is True
