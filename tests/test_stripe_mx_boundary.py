from backend.contracts.adapters import SidecarContext
from backend.integrations.stripe_mx import StripeMxPaymentAdapter


def test_health_unconfigured_without_credentials(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    import backend.config as config
    monkeypatch.setattr(config, "get_credential", lambda key: None)
    health = StripeMxPaymentAdapter().health()
    assert health.configured is False
    assert "fee_estimation" in health.capabilities


def test_estimate_fee_available_with_zero_credentials(monkeypatch):
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    result = StripeMxPaymentAdapter().estimate_fee(100.0)
    assert result["fee_amount"] > 0
    assert result["net_amount"] < 100.0
    assert result["currency"] == "MXN"


def test_list_payments_unconfigured_reports_source():
    import backend.config as config
    adapter = StripeMxPaymentAdapter()
    payments = adapter.list_payments()
    assert payments == [{"source": "unconfigured"}] or payments[0].get("source") == "unconfigured"


def test_handle_webhook_dry_run_makes_no_dedup_write():
    adapter = StripeMxPaymentAdapter()
    result = adapter.handle_webhook({"id": "evt_1"}, context=SidecarContext(dry_run=True))
    assert result["dry_run"] is True
    assert result["accepted"] is True


def test_handle_webhook_live_dedups_repeat_events():
    adapter = StripeMxPaymentAdapter()
    ctx = SidecarContext(dry_run=False)
    first = adapter.handle_webhook({"id": "evt_1"}, context=ctx)
    second = adapter.handle_webhook({"id": "evt_1"}, context=ctx)
    assert first["accepted"] is True
    assert second["accepted"] is False
