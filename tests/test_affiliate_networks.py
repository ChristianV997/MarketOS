"""Tests for backend.integrations.affiliate_networks — dry-run convention,
recruitment rate-limiting, and attempt-cap safety rails.
"""
from datetime import datetime, timezone

import pytest

from backend.integrations.affiliate_networks import (
    AffiliateNetwork,
    AffiliateNetworkConnector,
    AffiliateRecruitment,
    OrganicChannelExpander,
    _recruitment_attempts,
    _recruitment_limiter,
)


@pytest.fixture(autouse=True)
def _reset_recruitment_state():
    """Rate limiter and attempt counters are module-level singletons —
    reset between tests so they don't leak across test order."""
    _recruitment_attempts.clear()
    _recruitment_limiter.last_run = 0.0
    yield
    _recruitment_attempts.clear()
    _recruitment_limiter.last_run = 0.0


def _recruitment(product_id: str = "product_1") -> AffiliateRecruitment:
    return AffiliateRecruitment(
        product_id=product_id,
        network=AffiliateNetwork.IMPACT,
        requested_at=datetime.now(timezone.utc),
        affiliate_template="template",
    )


# ── dry-run convention ────────────────────────────────────────────────────────

def test_connector_defaults_to_module_dry_run_switch(monkeypatch):
    monkeypatch.setattr("backend.integrations.affiliate_networks._DRY_RUN", True)
    connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT)
    assert connector.dry_run is True


def test_connector_explicit_dry_run_overrides_module_switch(monkeypatch):
    monkeypatch.setattr("backend.integrations.affiliate_networks._DRY_RUN", True)
    connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT, dry_run=False)
    assert connector.dry_run is False


def test_expander_defaults_to_module_dry_run_switch(monkeypatch):
    monkeypatch.setattr("backend.integrations.affiliate_networks._DRY_RUN", True)
    expander = OrganicChannelExpander()
    assert expander.dry_run is True
    assert all(c.dry_run is True for c in expander.connectors.values())


# ── recruitment rate limiting ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recruit_affiliates_dry_run_bypasses_rate_limit_and_cap():
    connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT, dry_run=True)
    success, msg = await connector.recruit_affiliates(_recruitment())
    assert success is True
    assert "Dry-run" in msg


@pytest.mark.asyncio
async def test_recruit_affiliates_live_path_rate_limited_on_second_call():
    connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT, dry_run=False)
    first_success, first_msg = await connector.recruit_affiliates(_recruitment())
    # First call: not rate-limited (limiter starts "ready"), but no real
    # network client exists yet, so it degrades gracefully.
    assert first_success is False
    assert "not yet implemented" in first_msg

    second_success, second_msg = await connector.recruit_affiliates(_recruitment())
    assert second_success is False
    assert "rate-limited" in second_msg


# ── recruitment attempt cap ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recruit_affiliates_live_path_respects_attempt_cap(monkeypatch):
    connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT, dry_run=False)
    monkeypatch.setattr(
        "backend.integrations.affiliate_networks._MAX_RECRUITMENT_ATTEMPTS", 2,
    )
    # Bypass the rate limiter between calls so only the attempt cap is exercised.
    monkeypatch.setattr(_recruitment_limiter, "ready", lambda: True)

    for _ in range(2):
        success, msg = await connector.recruit_affiliates(_recruitment())
        assert success is False
        assert "not yet implemented" in msg

    success, msg = await connector.recruit_affiliates(_recruitment())
    assert success is False
    assert "attempt cap" in msg


@pytest.mark.asyncio
async def test_recruitment_attempts_tracked_per_product_and_network(monkeypatch):
    monkeypatch.setattr(_recruitment_limiter, "ready", lambda: True)
    connector = AffiliateNetworkConnector(AffiliateNetwork.IMPACT, dry_run=False)

    await connector.recruit_affiliates(_recruitment("product_a"))
    await connector.recruit_affiliates(_recruitment("product_b"))

    assert _recruitment_attempts[("product_a", "impact")] == 1
    assert _recruitment_attempts[("product_b", "impact")] == 1
