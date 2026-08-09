"""Tests for services.customer_intelligence.publicity_plan.build_publicity_strategy."""
from services.customer_intelligence.publicity_plan import build_publicity_strategy


def test_returns_ad_angles_pr_angles_and_channels():
    result = build_publicity_strategy("shop")
    assert result.ad_angles
    assert result.pr_angles
    assert result.channels


def test_never_raises_when_ad_angle_generation_fails(monkeypatch):
    monkeypatch.setattr(
        "services.creative_growth.generate_ad_angles",
        lambda business_type: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = build_publicity_strategy("shop")
    assert result.ad_angles  # falls back to defaults
