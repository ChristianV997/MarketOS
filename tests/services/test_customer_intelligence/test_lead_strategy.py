"""Tests for services.customer_intelligence.lead_strategy.build_lead_strategy."""
from services.customer_intelligence.lead_strategy import build_lead_strategy


def test_low_budget_gets_organic_only_sources():
    result = build_lead_strategy("shop", budget_tier="low")
    assert "paid social (Meta/TikTok)" not in result.lead_sources


def test_medium_budget_adds_paid_social():
    result = build_lead_strategy("shop", budget_tier="medium")
    assert "paid social (Meta/TikTok)" in result.lead_sources


def test_high_budget_adds_paid_search_and_sdr_outbound():
    result = build_lead_strategy("shop", budget_tier="high")
    assert "paid search" in result.lead_sources
    assert "SDR outbound (phone/WhatsApp)" in result.outreach_channels


def test_existing_audience_prioritizes_reactivation():
    result = build_lead_strategy("shop", has_existing_audience=True)
    assert result.lead_sources[0] == "existing customer/audience reactivation"


def test_qualification_questions_always_present():
    result = build_lead_strategy("shop")
    assert result.qualification_questions
