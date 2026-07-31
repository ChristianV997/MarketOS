"""Tests for backend.monitoring.alerts and backend.reporting.weekly_report."""
import time
import uuid

import pytest

import backend.metrics.campaign_metrics as cm
import backend.monitoring.alerts as alerts_mod
from backend.core.persistence import save_json_atomic


@pytest.fixture
def isolated_alerts(monkeypatch, tmp_path):
    """Private alert log + cooldown state + metric log + event store per
    test — the event store in particular is a real shared file
    (state/workflow_executions.jsonl) that every workflow-journaling call
    across the whole test suite writes to, so the stuck_workflow and
    supplier_placement_failures checks would otherwise see cross-test
    pollution instead of just this test's state."""
    monkeypatch.setattr(alerts_mod, "_ALERTS_PATH", tmp_path / "alerts.jsonl")
    monkeypatch.setattr(alerts_mod, "_COOLDOWN_STATE", str(tmp_path / "cooldowns.json"))
    monkeypatch.setattr(cm, "_METRICS_PATH", tmp_path / "metrics.jsonl")

    from backend.orchestration.event_store import event_store
    monkeypatch.setattr(event_store, "path", str(tmp_path / "events.jsonl"))

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


class TestStuckWorkflowAlert:
    def test_fires_for_a_workflow_stuck_past_the_age_threshold(self, isolated_alerts, monkeypatch):
        import importlib
        es_mod = importlib.import_module("backend.orchestration.event_store")

        monkeypatch.setattr(alerts_mod, "_STUCK_WORKFLOW_MIN_AGE_S", 1.0)
        from backend.orchestration.event_store import event_store, new_workflow_id
        wid = new_workflow_id("fulfillment")
        # Backdate the append instead of sleeping past the age threshold —
        # restored immediately after, without disturbing isolated_alerts'
        # other monkeypatches (a bare monkeypatch.undo() here would revert
        # those too).
        real_time = es_mod.time.time
        es_mod.time.time = lambda: real_time() - 1.1
        try:
            event_store.append(wid, "workflow_started", workflow="fulfillment",
                               step="place_order", data={"order_id": "crashed_order"})
        finally:
            es_mod.time.time = real_time

        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"] == "stuck_workflow" for a in fired)

    def test_recent_workflow_does_not_fire(self, isolated_alerts, monkeypatch):
        monkeypatch.setattr(alerts_mod, "_STUCK_WORKFLOW_MIN_AGE_S", 600.0)
        from backend.orchestration.event_store import event_store, new_workflow_id
        wid = new_workflow_id("fulfillment")
        event_store.append(wid, "workflow_started", workflow="fulfillment",
                           step="place_order", data={})
        fired = alerts_mod.evaluate_alerts()
        assert not any(a["key"] == "stuck_workflow" for a in fired)

    def test_completed_workflow_does_not_fire(self, isolated_alerts, monkeypatch):
        import importlib
        es_mod = importlib.import_module("backend.orchestration.event_store")

        monkeypatch.setattr(alerts_mod, "_STUCK_WORKFLOW_MIN_AGE_S", 1.0)
        from backend.orchestration.event_store import event_store, new_workflow_id
        wid = new_workflow_id("fulfillment")
        real_time = es_mod.time.time
        es_mod.time.time = lambda: real_time() - 1.1
        try:
            event_store.append(wid, "workflow_started", workflow="fulfillment", step="place_order")
            event_store.append(wid, "workflow_completed", workflow="fulfillment", step="place_order")
        finally:
            es_mod.time.time = real_time
        fired = alerts_mod.evaluate_alerts()
        assert not any(a["key"] == "stuck_workflow" for a in fired)


class TestWebhookSignatureFailureAlert:
    def test_fires_once_threshold_crossed(self, isolated_alerts, monkeypatch):
        monkeypatch.setattr(alerts_mod, "_WEBHOOK_SIG_FAILURE_THRESHOLD", 3)
        from backend.orchestration.event_store import event_store, new_workflow_id
        for _ in range(3):
            event_store.append(new_workflow_id("webhooksig"), "webhook_signature_failed",
                               workflow="webhook_security", step="verify",
                               data={"source": "stripe"})
        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"] == "webhook_signature_failures" for a in fired)

    def test_below_threshold_does_not_fire(self, isolated_alerts, monkeypatch):
        monkeypatch.setattr(alerts_mod, "_WEBHOOK_SIG_FAILURE_THRESHOLD", 5)
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(new_workflow_id("webhooksig"), "webhook_signature_failed",
                           workflow="webhook_security", step="verify", data={})
        fired = alerts_mod.evaluate_alerts()
        assert not any(a["key"] == "webhook_signature_failures" for a in fired)

    def test_real_webhook_route_failure_feeds_the_alert(self, isolated_alerts, monkeypatch):
        """End-to-end: an actual invalid-signature request against the real
        webhook route feeds this alert, not just a hand-crafted event."""
        monkeypatch.setattr(alerts_mod, "_WEBHOOK_SIG_FAILURE_THRESHOLD", 1)
        monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

        from fastapi.testclient import TestClient
        from backend.api import app
        client = TestClient(app)
        resp = client.post("/webhooks/stripe", content=b"{}",
                           headers={"Stripe-Signature": "t=1,v1=deadbeef"})
        assert resp.status_code == 400

        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"] == "webhook_signature_failures" for a in fired)


class TestSupplierPlacementFailureAlert:
    def test_fires_above_failure_rate_threshold(self, isolated_alerts, monkeypatch):
        monkeypatch.setattr(alerts_mod, "_SUPPLIER_FAILURE_MIN_ATTEMPTS", 2)
        monkeypatch.setattr(alerts_mod, "_SUPPLIER_FAILURE_RATE_THRESHOLD", 0.5)
        from backend.orchestration.event_store import event_store, new_workflow_id
        for _ in range(3):
            wid = new_workflow_id("fulfillment")
            event_store.append(wid, "workflow_started", workflow="fulfillment", step="place_order")
            event_store.append(wid, "workflow_failed", workflow="fulfillment", step="place_order")
        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"] == "supplier_placement_failures" for a in fired)

    def test_below_min_attempts_does_not_fire(self, isolated_alerts, monkeypatch):
        monkeypatch.setattr(alerts_mod, "_SUPPLIER_FAILURE_MIN_ATTEMPTS", 10)
        from backend.orchestration.event_store import event_store, new_workflow_id
        wid = new_workflow_id("fulfillment")
        event_store.append(wid, "workflow_started", workflow="fulfillment", step="place_order")
        event_store.append(wid, "workflow_failed", workflow="fulfillment", step="place_order")
        fired = alerts_mod.evaluate_alerts()
        assert not any(a["key"] == "supplier_placement_failures" for a in fired)

    def test_healthy_placements_do_not_fire(self, isolated_alerts, monkeypatch):
        monkeypatch.setattr(alerts_mod, "_SUPPLIER_FAILURE_MIN_ATTEMPTS", 2)
        from backend.orchestration.event_store import event_store, new_workflow_id
        for _ in range(5):
            wid = new_workflow_id("fulfillment")
            event_store.append(wid, "workflow_started", workflow="fulfillment", step="place_order")
            event_store.append(wid, "workflow_completed", workflow="fulfillment", step="place_order")
        fired = alerts_mod.evaluate_alerts()
        assert not any(a["key"] == "supplier_placement_failures" for a in fired)


class TestCapitalDrawdownAlert:
    def test_fires_when_drawdown_exceeded(self, isolated_alerts, monkeypatch):
        from backend.api import _state

        monkeypatch.setattr(_state, "capital", 100.0, raising=False)
        monkeypatch.setattr(_state, "_peak_capital", 1000.0, raising=False)
        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"] == "capital_drawdown" for a in fired)

    def test_no_drawdown_does_not_fire(self, isolated_alerts, monkeypatch):
        from backend.api import _state

        monkeypatch.setattr(_state, "capital", 1000.0, raising=False)
        monkeypatch.setattr(_state, "_peak_capital", 1000.0, raising=False)
        fired = alerts_mod.evaluate_alerts()
        assert not any(a["key"] == "capital_drawdown" for a in fired)


class TestCriticalAlertNotification:
    def test_error_level_alert_triggers_slack_notify(self, isolated_alerts, monkeypatch):
        sent = []
        monkeypatch.setattr("backend.monitoring.alerting.send_slack",
                           lambda message: sent.append(message))
        monkeypatch.setattr("backend.monitoring.alerting.send_telegram", lambda message: None)
        monkeypatch.setattr(alerts_mod, "_SPEND_DAILY_CEILING", 100.0)

        cid = f"c_{uuid.uuid4().hex[:8]}"
        cm.record_metric(cid, "tiktok", "Big Spender", spend_usd=150.0, revenue_usd=300.0)
        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"] == "spend_burst" for a in fired)
        assert len(sent) == 1
        assert "spend_burst" not in sent[0]  # sanity: it's the message, not the key
        assert "daily spend" in sent[0]

    def test_warn_level_alert_does_not_notify(self, isolated_alerts, monkeypatch):
        sent = []
        monkeypatch.setattr("backend.monitoring.alerting.send_slack",
                           lambda message: sent.append(message))
        cid = f"c_{uuid.uuid4().hex[:8]}"
        cm.record_metric(cid, "tiktok", "Burning Widget", spend_usd=60.0, revenue_usd=6.0)
        fired = alerts_mod.evaluate_alerts()
        assert any(a["key"].startswith("roas_floor") for a in fired)  # a "warn"-level alert
        assert sent == []

    def test_notify_failure_does_not_break_evaluation(self, isolated_alerts, monkeypatch):
        def boom(message):
            raise RuntimeError("slack webhook down")
        monkeypatch.setattr("backend.monitoring.alerting.send_slack", boom)
        monkeypatch.setattr(alerts_mod, "_SPEND_DAILY_CEILING", 100.0)

        cid = f"c_{uuid.uuid4().hex[:8]}"
        cm.record_metric(cid, "tiktok", "Big Spender", spend_usd=150.0, revenue_usd=300.0)
        fired = alerts_mod.evaluate_alerts()  # must not raise
        assert any(a["key"] == "spend_burst" for a in fired)


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
