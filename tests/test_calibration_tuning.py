"""Tests for backend.metrics.calibration_tuning — confidence vs. reality."""
import pytest

import backend.metrics.calibration_tuning as ct


@pytest.fixture
def seeded(monkeypatch):
    """Deterministic calibration records + launch confidences."""
    def _confidence():
        return {"HighConf": 0.92, "MidConf": 0.8, "LowConf": 0.65}

    def _records(max_records=500):
        # (product, predicted, actual): high-confidence products do better
        rows = []
        for _ in range(4):
            rows.append({"product": "HighConf", "predicted": 2.0, "actual": 2.4,
                         "error": -0.4, "ts": 0})
            rows.append({"product": "MidConf", "predicted": 2.0, "actual": 1.5,
                         "error": 0.5, "ts": 0})
            rows.append({"product": "LowConf", "predicted": 2.0, "actual": 0.7,
                         "error": 1.3, "ts": 0})
        return rows

    monkeypatch.setattr(ct, "_product_confidence", _confidence)
    monkeypatch.setattr(ct, "_paired_records", _records)


def test_insufficient_data(monkeypatch):
    monkeypatch.setattr(ct, "_product_confidence", dict)
    monkeypatch.setattr(ct, "_paired_records", lambda max_records=500: [])
    report = ct.confidence_report()
    assert report["status"] == "insufficient_data"
    assert report["roas_prior_correction"] == 1.0


def test_buckets_and_monotonicity(seeded):
    report = ct.confidence_report()
    assert report["status"] == "ok"
    assert report["samples"] == 12
    labels = [b["bucket"] for b in report["buckets"]]
    assert labels == ["0.6-0.75", "0.75-0.9", "0.9-1.0"]
    actuals = [b["avg_actual"] for b in report["buckets"]]
    assert actuals == sorted(actuals)          # higher confidence → higher ROAS
    assert report["monotonic"] is True


def test_recommended_threshold(seeded):
    """Lowest reliable bucket clearing breakeven: MidConf's (0.75)."""
    report = ct.confidence_report()
    assert report["recommended_green_threshold"] == 0.75


def test_prior_correction_direction(seeded):
    """Priors ran hot overall (mean actual 1.53 vs predicted 2.0) → correction <1."""
    report = ct.confidence_report()
    assert 0.7 < report["roas_prior_correction"] < 0.8
    assert 0.7 < ct.prior_correction() < 0.8


def test_prior_correction_clamped(monkeypatch):
    monkeypatch.setattr(ct, "_product_confidence", lambda: {"P": 0.9})
    monkeypatch.setattr(ct, "_paired_records", lambda max_records=500: [
        {"product": "P", "predicted": 0.1, "actual": 5.0, "error": -4.9, "ts": 0}
        for _ in range(10)
    ])
    assert ct.prior_correction() == 4.0        # raw 50× clamps to 4.0


def test_non_monotonic_flagged(monkeypatch):
    monkeypatch.setattr(ct, "_product_confidence",
                        lambda: {"High": 0.95, "Low": 0.65})
    monkeypatch.setattr(ct, "_paired_records", lambda max_records=500: (
        [{"product": "High", "predicted": 2.0, "actual": 0.5, "error": 1.5, "ts": 0}] * 4
        + [{"product": "Low", "predicted": 2.0, "actual": 2.5, "error": -0.5, "ts": 0}] * 4
    ))
    report = ct.confidence_report()
    assert report["monotonic"] is False
    assert "does NOT rank" in report["rationale"]
