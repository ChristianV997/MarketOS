"""tests/benchmarks/test_commercial_replay_lab.py — Test commercial replay laboratory suite.

Validates:
1. Scenario replay laboratory runs all 5 scenarios with replay_equal == True.
2. Achieved stages strictly match canonical expectations.
3. 7-dimensional sensitivity matrix executes cleanly across all 7 dimensions.
4. Scaling profiler returns valid timings and positive throughput.
5. Statistical comparison produces 0 hash sequence drift.
6. Zero live authority violations across all generated events.
"""
from __future__ import annotations

from decimal import Decimal

from scripts.benchmarks.benchmark_commercial_replay_lab import (
    EXPECTED_STAGES,
    ScenarioReplayLaboratory,
    SensitivityMatrixLaboratory,
    ScalingAndProfilerLaboratory,
    StatisticalComparisonLaboratory,
)


def test_scenario_replay_laboratory_all_five_scenarios():
    records = ScenarioReplayLaboratory.run_scenarios()
    assert len(records) == 5

    for rec in records:
        assert rec.replay_equal is True
        assert rec.first_replay_hash == rec.second_replay_hash
        assert rec.first_replay_hash != ""
        assert rec.event_count == 17
        assert rec.achievable_stage == EXPECTED_STAGES[rec.scenario_id]
        assert rec.live_authority_violations == ()
        assert rec.live_actions_taken is False
        assert rec.sequence_issues == ()
        assert rec.wall_ms > 0
        assert rec.output_bytes > 0


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


def test_statistical_comparison_laboratory_zero_drift():
    summary, cycle_times = StatisticalComparisonLaboratory.run_repeated_cycles(iterations=3)
    assert summary.iterations == 3
    assert summary.total_runs == 15
    assert len(cycle_times) == 3
    assert summary.hash_drift_detected is False
    assert summary.mean_cycle_ms > 0
    assert summary.median_cycle_ms > 0
    assert summary.min_cycle_ms <= summary.max_cycle_ms


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
    if result["status"] == "available":
        assert result["result"] == "actual"
        assert result["rows_evaluated"] == 5
        assert result["all_replay_equal"] is True
        assert result["all_launch_blocked"] is True


def test_adversarial_authority_fail_closed_rejection():
    res = ScenarioReplayLaboratory.verify_adversarial_authority_rejection()
    assert res["adversarial_events_tested"] == 2
    assert res["fail_closed"] is True
    assert len(res["violations_detected"]) == 2
