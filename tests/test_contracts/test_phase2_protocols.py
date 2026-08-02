"""Structural conformance tests for the Phase 2 Protocols added to
backend.contracts.adapters: CRMProvider (no concrete adapter — Twenty is
deferred/AGPL), ConversationProvider, AnalyticsProvider,
MarketingAutomationProvider, CustomerAutomationProvider, HostingProvider."""
from backend.contracts.adapters import (
    AdapterHealth,
    AnalyticsProvider,
    ConversationProvider,
    CustomerAutomationProvider,
    HostingProvider,
    MarketingAutomationProvider,
    SidecarContext,
)
from backend.integrations.activepieces import ActivepiecesAutomationAdapter
from backend.integrations.chatwoot import ChatwootConversationAdapter
from backend.integrations.hostinger import HostingerHostingAdapter
from backend.integrations.mautic import MauticMarketingAutomationAdapter
from backend.integrations.posthog_backend import PostHogAnalyticsAdapter


def test_chatwoot_satisfies_conversation_provider_protocol():
    adapter: ConversationProvider = ChatwootConversationAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    ctx = SidecarContext(dry_run=True)
    assert isinstance(adapter.create_contact({}, context=ctx), dict)
    assert isinstance(adapter.create_conversation({}, context=ctx), dict)
    assert isinstance(adapter.send_message_draft("c1", {}, context=ctx), dict)
    assert isinstance(adapter.record_inbound_message("c1", {}, context=ctx), dict)
    assert isinstance(adapter.handoff_to_human("c1", context=ctx), dict)


def test_mautic_satisfies_marketing_automation_provider_protocol():
    adapter: MarketingAutomationProvider = MauticMarketingAutomationAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    ctx = SidecarContext(dry_run=True)
    assert isinstance(adapter.upsert_contact({}, context=ctx), dict)
    assert isinstance(adapter.add_to_segment("c1", "seg1", context=ctx), dict)
    assert isinstance(adapter.trigger_campaign("camp1", "c1", context=ctx), dict)
    assert isinstance(adapter.record_email_event({"id": "e1"}, context=ctx), dict)


def test_activepieces_satisfies_customer_automation_provider_protocol():
    adapter: CustomerAutomationProvider = ActivepiecesAutomationAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    assert isinstance(adapter.trigger_workflow("wf1", {}, context=SidecarContext(dry_run=True)), dict)


def test_posthog_satisfies_analytics_provider_protocol():
    adapter: AnalyticsProvider = PostHogAnalyticsAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    ctx = SidecarContext(dry_run=True)
    assert isinstance(adapter.capture_event({}, context=ctx), dict)
    assert isinstance(adapter.query_funnel({}), dict)
    assert isinstance(adapter.query_events(event_name="service_run"), list)


def test_hostinger_satisfies_hosting_provider_protocol():
    adapter: HostingProvider = HostingerHostingAdapter()
    assert isinstance(adapter.health(), AdapterHealth)
    assert isinstance(adapter.get_status(), dict)
    assert isinstance(adapter.list_sites(), list)
    assert isinstance(adapter.get_plan_usage(), dict)
