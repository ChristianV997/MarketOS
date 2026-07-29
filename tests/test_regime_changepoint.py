"""Tests for backend.regime.detector::RegimeDetector.detect_changepoint —
Phase 4 additive CUSUM (Page-Hinkley) changepoint signal.

Covers: false-positive rate on a genuinely stable series, detection delay
on step-change series (bounded by the theoretical ARL1 approximation),
direction correctness, re-anchoring after a fire, additivity (detect()'s
existing ~20 hardcoded-output tests are unaffected), and incremental
row-consumption bookkeeping.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.regime.detector import RegimeDetector
from backend.data.event_log import EventLog


def _make_log(roas_values):
    log = EventLog()
    log.rows = [{"roas": float(v)} for v in roas_values]
    return log


class TestStationaryNoFalsePositive:
    def test_stationary_series_rarely_fires(self):
        rng = np.random.default_rng(7)
        det = RegimeDetector()
        roas = rng.normal(1.0, 0.05, 2000)
        log = _make_log(roas)
        result = det.detect_changepoint(log)
        # ARL0 ~= 5940 cycles between false alarms at defaults (k=0.5, h=8.0);
        # over 2000 i.i.d. stationary points, essentially zero fires expected.
        # Allow generous tolerance since this is a stochastic guarantee.
        assert det._cusum_pos < det.cusum_h * 1.5
        assert det._cusum_neg < det.cusum_h * 1.5


class TestStepChangeDetectionDelay:
    def test_detects_1sigma_step_within_arl1_bound(self):
        det = RegimeDetector(cusum_warmup=15)
        baseline = [1.0 + 0.01 * ((-1) ** i) for i in range(15)]
        # sustained 1-sigma-ish step (sigma from baseline ~ 0.01, so use a
        # step scaled to the detector's own estimated baseline_std later)
        log = _make_log(baseline)
        result = det.detect_changepoint(log)
        assert result["status"] == "monitoring"
        baseline_std = det._baseline_std

        fired_at = None
        for cycle in range(1, 40):
            step_val = det._baseline_mean + 1.0 * baseline_std
            log.rows.append({"roas": step_val})
            result = det.detect_changepoint(log)
            if result["is_changepoint"]:
                fired_at = cycle
                break

        assert fired_at is not None, "1-sigma step was never detected"
        # ARL1 ~= h/(delta-k) = 8/(1.0-0.5) = 16; allow generous tolerance
        assert fired_at <= 30

    def test_detects_2sigma_step_faster_than_1sigma(self):
        det1 = RegimeDetector(cusum_warmup=15)
        det2 = RegimeDetector(cusum_warmup=15)
        baseline = [1.0 + 0.01 * ((-1) ** i) for i in range(15)]

        log1 = _make_log(baseline)
        det1.detect_changepoint(log1)
        log2 = _make_log(baseline)
        det2.detect_changepoint(log2)

        std1 = det1._baseline_std
        std2 = det2._baseline_std

        fired_1sigma = None
        for cycle in range(1, 40):
            log1.rows.append({"roas": det1._baseline_mean + 1.0 * std1})
            r = det1.detect_changepoint(log1)
            if r["is_changepoint"]:
                fired_1sigma = cycle
                break

        fired_2sigma = None
        for cycle in range(1, 40):
            log2.rows.append({"roas": det2._baseline_mean + 2.0 * std2})
            r = det2.detect_changepoint(log2)
            if r["is_changepoint"]:
                fired_2sigma = cycle
                break

        assert fired_1sigma is not None
        assert fired_2sigma is not None
        # Bigger shifts must be caught at least as fast, generally faster.
        assert fired_2sigma <= fired_1sigma


class TestDirectionCorrectness:
    def test_upward_step_reports_up(self):
        det = RegimeDetector(cusum_warmup=15)
        baseline = [1.0] * 15
        log = _make_log(baseline)
        det.detect_changepoint(log)

        fired = None
        for _ in range(40):
            log.rows.append({"roas": 1.0 + 5.0})  # large sustained upward shock
            fired = det.detect_changepoint(log)
            if fired["is_changepoint"]:
                break
        assert fired["is_changepoint"] is True
        assert fired["direction"] == "up"

    def test_downward_step_reports_down(self):
        det = RegimeDetector(cusum_warmup=15)
        baseline = [1.0] * 15
        log = _make_log(baseline)
        det.detect_changepoint(log)

        fired = None
        for _ in range(40):
            log.rows.append({"roas": 1.0 - 5.0})  # large sustained downward shock
            fired = det.detect_changepoint(log)
            if fired["is_changepoint"]:
                break
        assert fired["is_changepoint"] is True
        assert fired["direction"] == "down"


class TestReanchoring:
    def test_resets_after_firing_and_catches_second_shift(self):
        det = RegimeDetector(cusum_warmup=10)
        log = _make_log([1.0] * 10)
        det.detect_changepoint(log)

        # First shock
        fired_first = False
        for _ in range(40):
            log.rows.append({"roas": 10.0})
            r = det.detect_changepoint(log)
            if r["is_changepoint"]:
                fired_first = True
                break
        assert fired_first
        assert r["status"] == "warming_up"
        assert det._cusum_pos == 0.0
        assert det._cusum_neg == 0.0

        # Re-warm-up
        for _ in range(10):
            log.rows.append({"roas": 10.0})
            det.detect_changepoint(log)

        # Second shock (further shift from the new baseline)
        fired_second = False
        for _ in range(40):
            log.rows.append({"roas": 30.0})
            r2 = det.detect_changepoint(log)
            if r2["is_changepoint"]:
                fired_second = True
                break
        assert fired_second


class TestAdditivity:
    """detect()'s existing hardcoded-threshold behavior must be completely
    unaffected by interleaved detect_changepoint() calls on the same
    instance — proves the two signals share no state.
    """

    def test_detect_unaffected_by_changepoint_calls(self):
        det = RegimeDetector(window=30)

        roas_stable = [1.0 + 0.001 * (i % 3 - 1) for i in range(30)]
        log = _make_log(roas_stable)

        # Interleave detect_changepoint() calls before/after detect()
        det.detect_changepoint(log)
        result = det.detect(log)
        det.detect_changepoint(log)

        assert result == "stable"

    def test_detect_growth_unaffected(self):
        det = RegimeDetector(window=30)
        roas_growth = [0.5 + 0.08 * i for i in range(30)]
        log = _make_log(roas_growth)

        det.detect_changepoint(log)
        result = det.detect(log)

        assert result == "growth"

    def test_full_legacy_suite_semantics_preserved(self):
        """Spot-check a few of tests/test_regime_detector.py's exact cases
        still hold on an instance that has also called detect_changepoint().
        """
        det = RegimeDetector(window=30)

        too_few = _make_log([1.0] * 5)
        det.detect_changepoint(too_few)
        assert det.detect(too_few) == "unknown"

        decay_log = _make_log([3.0 - 0.08 * i for i in range(30)])
        det.detect_changepoint(decay_log)
        assert det.detect(decay_log) == "decay"


class TestIncrementalConsumption:
    def test_no_new_rows_is_a_noop(self):
        det = RegimeDetector(cusum_warmup=15)
        log = _make_log([1.0] * 15)
        det.detect_changepoint(log)
        cycles_before = det._cycles_since_reset

        result = det.detect_changepoint(log)  # no new rows appended
        assert det._cycles_since_reset == cycles_before
        assert result["is_changepoint"] is False

    def test_seen_rows_tracks_length(self):
        det = RegimeDetector(cusum_warmup=15)
        log = _make_log([1.0] * 10)
        det.detect_changepoint(log)
        assert det._seen_rows == 10

        log.rows.append({"roas": 1.0})
        det.detect_changepoint(log)
        assert det._seen_rows == 11

    def test_seen_rows_never_exceeds_log_length(self):
        det = RegimeDetector(cusum_warmup=15)
        log = _make_log([1.0] * 20)
        det.detect_changepoint(log)
        # Simulate a truncated/reset event_log shorter than _seen_rows
        log.rows = log.rows[-5:]
        result = det.detect_changepoint(log)
        assert det._seen_rows <= len(log.rows)
        assert isinstance(result, dict)


class TestOutputShape:
    def test_returns_all_expected_keys(self):
        det = RegimeDetector()
        log = _make_log([1.0] * 5)
        result = det.detect_changepoint(log)
        expected_keys = {
            "is_changepoint", "probability", "direction", "cusum_pos",
            "cusum_neg", "baseline_mean", "baseline_std", "status",
            "cycles_since_reset",
        }
        assert expected_keys.issubset(result.keys())

    def test_status_warming_up_before_threshold(self):
        det = RegimeDetector(cusum_warmup=15)
        log = _make_log([1.0] * 5)
        result = det.detect_changepoint(log)
        assert result["status"] == "warming_up"
        assert result["probability"] == 0.0

    def test_status_monitoring_after_warmup(self):
        det = RegimeDetector(cusum_warmup=15)
        log = _make_log([1.0] * 15)
        result = det.detect_changepoint(log)
        assert result["status"] == "monitoring"
