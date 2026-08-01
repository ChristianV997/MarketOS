import pytest

from backend.contracts.adapters import SidecarContext
from backend.integrations.mautic import MauticMarketingAutomationAdapter


def test_health_unconfigured_without_env_vars(monkeypatch):
    monkeypatch.delenv("MAUTIC_BASE_URL", raising=False)
    monkeypatch.delenv("MAUTIC_USERNAME", raising=False)
    monkeypatch.delenv("MAUTIC_PASSWORD", raising=False)
    health = MauticMarketingAutomationAdapter().health()
    assert health.configured is False


def test_upsert_contact_dry_run_makes_no_http_call():
    class Client:
        def request(self, *args, **kwargs):
            raise AssertionError("dry-run must not make HTTP calls")

    adapter = MauticMarketingAutomationAdapter(client=Client())
    result = adapter.upsert_contact({"email": "a@example.com"}, context=SidecarContext(dry_run=True, idempotency_key="a"))
    assert result["dry_run"] is True


def test_trigger_campaign_requires_approval_when_live():
    adapter = MauticMarketingAutomationAdapter()
    with pytest.raises(PermissionError):
        adapter.trigger_campaign("camp-1", "contact-1", context=SidecarContext(dry_run=False, idempotency_key="a"))


def test_record_email_event_dedups_repeat_events():
    adapter = MauticMarketingAutomationAdapter()
    ctx = SidecarContext(dry_run=False)
    first = adapter.record_email_event({"id": "evt-1"}, context=ctx)
    second = adapter.record_email_event({"id": "evt-1"}, context=ctx)
    assert first["accepted"] is True
    assert second["accepted"] is False
