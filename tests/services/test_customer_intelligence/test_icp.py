"""Tests for services.customer_intelligence.icp."""
from services.customer_intelligence.icp import generate_customer_segments, generate_icp


class TestGenerateICP:
    def test_returns_buyer_profile_and_pain_points(self):
        icp = generate_icp("clinic", target_geo="MX", category="general")
        assert icp.business_type == "clinic"
        assert icp.buyer_profile["geo"] == "MX"
        assert icp.pain_points

    def test_price_sensitivity_scales_with_price_point(self):
        cheap = generate_icp("shop", price_point=100.0)
        expensive = generate_icp("shop", price_point=10000.0)
        assert cheap.buyer_profile["price_sensitivity"] == "high"
        assert expensive.buyer_profile["price_sensitivity"] == "low"

    def test_uses_real_category_priors_when_available(self, monkeypatch):
        monkeypatch.setattr("backend.data.category_priors.category_prior", lambda category, field, default: 0.42)
        icp = generate_icp("shop", category="consumables")
        assert icp.buyer_profile["repeat_purchase_likelihood"] == 0.42
        assert "category_priors" in icp.data_sources[0]

    def test_never_raises_when_category_priors_fails(self, monkeypatch):
        def _boom(category, field, default):
            raise RuntimeError("boom")
        monkeypatch.setattr("backend.data.category_priors.category_prior", _boom)
        icp = generate_icp("shop")
        assert "unknown" in str(icp.buyer_profile["repeat_purchase_likelihood"])


class TestGenerateCustomerSegments:
    def test_returns_three_segments_summing_to_100_pct(self):
        segments = generate_customer_segments("shop")
        total = sum(s["estimated_share_pct"] for s in segments.segments)
        assert total == 100.0

    def test_at_least_one_primary_segment(self):
        segments = generate_customer_segments("shop")
        assert any(s["priority"] == "primary" for s in segments.segments)
