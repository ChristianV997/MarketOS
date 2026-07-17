"""Tests for the Phase-2 orchestrator workers: budget scaling + alerting."""
import time
import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.optimization.budget_scaling as bs
import orchestrator.main as om


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(cm, "_METRICS_PATH", tmp_path / "metrics.jsonl")
    monkeypatch.setattr(bs, "_DECISIONS_PATH", tmp_path / "decisions.jsonl")
    return tmp_path


def test_budget_scaling_rate_limited(monkeypatch):
    monkeypatch.setattr(om, "_last_budget_scaling_ts", time.time())
    assert om._run_budget_scaling() == {"status": "skipped", "reason": "rate_limited"}


def test_budget_scaling_updates_artifacts(isolated, monkeypatch):
    cid = f"c_{uuid.uuid4().hex[:8]}"
    cm.record_metric(cid, "tiktok", "Scaler Widget", spend_usd=50.0, revenue_usd=150.0)
    monkeypatch.setattr(bs, "_current_budgets", lambda: {cid: 40.0})
    monkeypatch.setattr(om, "_last_budget_scaling_ts", 0.0)

    artifact = om._CampaignArtifact(
        campaign_id=cid, adgroup_id="ag", ad_ids=["a"], product="Scaler Widget",
        hook="h", angle="a", phase="DROPSHIP", estimated_roas=2.0, budget=40.0,
    )
    om._campaign_artifacts[cid] = artifact
    try:
        result = om._run_budget_scaling()
        assert result["status"] == "ok"
        assert result["decisions"] >= 1
        assert artifact.budget == 48.0        # 40 × 1.2 mirrored onto the artifact
    finally:
        om._campaign_artifacts.pop(cid, None)


def test_alerting_rate_limited(monkeypatch):
    monkeypatch.setattr(om, "_last_alerting_ts", time.time())
    assert om._run_alerting() == {"status": "skipped", "reason": "rate_limited"}


def test_alerting_runs(monkeypatch, tmp_path):
    import backend.monitoring.alerts as alerts_mod
    monkeypatch.setattr(alerts_mod, "_ALERTS_PATH", tmp_path / "alerts.jsonl")
    monkeypatch.setattr(alerts_mod, "_COOLDOWN_STATE", str(tmp_path / "cd.json"))
    monkeypatch.setattr(om, "_last_alerting_ts", 0.0)
    result = om._run_alerting()
    assert result["status"] == "ok"
    assert "alerts_fired" in result


def test_metrics_worker_records_campaign_metrics(isolated, monkeypatch):
    """The metrics-ingestion worker persists per-campaign rows with product
    attribution and prorated spend."""
    cid = f"dry_{uuid.uuid4().hex[:8]}"
    artifact = om._CampaignArtifact(
        campaign_id=cid, adgroup_id="ag", ad_ids=["a"], product="Attr Widget",
        hook="h", angle="a", phase="DROPSHIP", estimated_roas=2.0, budget=86.4,
    )
    om._campaign_artifacts[cid] = artifact
    om._campaign_platforms[cid] = "meta"
    om._campaign_last_metric_ts.pop(cid, None)

    monkeypatch.setattr("backend.integrations.tiktok_ads.fetch_roas",
                        lambda ids: {cid: 2.5})
    try:
        result = om._run_metrics_ingestion()
        assert result["status"] == "ok"
        rows = [r for r in cm._read_rows() if r["campaign_id"] == cid]
        assert len(rows) == 1
        row = rows[0]
        assert row["product"] == "Attr Widget"
        assert row["platform"] == "meta"
        # First observation assumes a 1h window: 86.4/day → 3.6 spend
        assert row["spend_usd"] == pytest.approx(3.6, rel=0.05)
        assert row["revenue_usd"] == pytest.approx(9.0, rel=0.05)
    finally:
        om._campaign_artifacts.pop(cid, None)
        om._campaign_platforms.pop(cid, None)
        om._campaign_last_metric_ts.pop(cid, None)
