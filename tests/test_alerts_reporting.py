"""Tests for backend.monitoring.alerts and backend.reporting.weekly_report."""
import time
import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.monitoring.alerts as alerts_mod
from backend.core.persistence import save_json_atomic


@pytest.fixture
def isolated_alerts(monkeypatch, tmp_path):
    """Private alert log + cooldown state + metric log per test."""
    monkeypatch.setattr(alerts_mod, "_ALERTS_PATH", tmp_path / "alerts.jsonl")
    monkeypatch.setattr(alerts_mod, "_COOLDOWN_STATE", str(tmp_path / "cooldowns.json"))
    monkeypatch.setattr(cm, "_METRICS_PATH", tmp_path / "metrics.jsonl")
    return tmp_path


def test_roas_floor_alert_fires(isolated_alerts):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Burning Widget", spend_usd=60.0, revenue_usd=6.0)
    fired = alerts_mod.evaluate_alerts()
    keys = {a["key"] for a in fired}
    assert f"roas_floor:{cid}" in keys


def test_cooldown_suppresses_refire(isolated_alerts):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Burning Widget", spend_usd=60.0, revenue_usd=6.0)
    first = alerts_mod.evaluate_alerts()
    second = alerts_mod.evaluate_alerts()
    assert any(a["key"] == f"roas_floor:{cid}" for a in first)
    assert not any(a["key"] == f"roas_floor:{cid}" for a in second)


def test_spend_burst_alert(isolated_alerts, monkeypatch):
    monkeypatch.setattr(alerts_mod, "_SPEND_DAILY_CEILING", 100.0)
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Big Spender", spend_usd=150.0, revenue_usd=300.0)
    fired = alerts_mod.evaluate_alerts()
    assert any(a["key"] == "spend_burst" for a in fired)


def test_healthy_state_fires_nothing(isolated_alerts):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Fine Widget", spend_usd=30.0, revenue_usd=60.0)
    fired = alerts_mod.evaluate_alerts()
    assert not any(a["key"].startswith("roas_floor") or a["key"] == "spend_burst"
                   for a in fired)


def test_alert_summary_aggregates(isolated_alerts):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Burning Widget", spend_usd=60.0, revenue_usd=6.0)
    alerts_mod.evaluate_alerts()
    summary = alerts_mod.alert_summary(lookback_hours=1)
    assert summary["total_alerts"] >= 1
    assert summary["by_level"].get("warn", 0) >= 1
    assert summary["alerts"][0]["ts"] <= time.time()


# ── weekly report ─────────────────────────────────────────────────────────────

def test_generate_report_sections(monkeypatch, tmp_path):
    import backend.reporting.weekly_report as wr
    monkeypatch.setattr(wr, "_REPORT_DIR", tmp_path / "reports")

    report = wr.generate_report(period_days=7)
    for section in ("profitability", "forecast", "costs", "errors",
                    "scaling", "calibration", "alerts", "headline"):
        assert section in report
    assert report["period_days"] == 7
    assert "total_profit" in report["headline"]
    assert report["persisted_to"].endswith(".json")


def test_latest_report_roundtrip(monkeypatch, tmp_path):
    import backend.reporting.weekly_report as wr
    monkeypatch.setattr(wr, "_REPORT_DIR", tmp_path / "reports")

    assert wr.latest_report() is None
    generated = wr.generate_report(period_days=3)
    loaded = wr.latest_report()
    assert loaded is not None
    assert loaded["period_days"] == 3
    assert loaded["generated_at"] == generated["generated_at"]
