"""Tests for GET /api/events/competition-evidence and
/api/events/competition-summaries — thin filter + decoded summary views,
following the same pattern as the supplier-evidence/opportunity-scoring
read routes."""
from api.routes import canonical_events


def test_competition_evidence_route_filters_to_competition_event_types(monkeypatch):
    fake_events = [
        {"event_type": "commerce_mvp_run_started", "payload_summary": {}},
        {"event_type": "competition_observed", "payload_summary": {}},
        {"event_type": "competition_summary_created", "payload_summary": {}},
        {"event_type": "market_pricing_computed", "payload_summary": {}},
        {"event_type": "market_intelligence_completed", "payload_summary": {}},
        {"event_type": "opportunity_scoring_started", "payload_summary": {}},
        {"event_type": "shopify_product_observed", "payload_summary": {}},
    ]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"timeline": {"events": fake_events}})
    result = canonical_events.competition_evidence(limit=100, offset=0, request=None)
    types = {event["event_type"] for event in result["events"]}
    assert types == {"competition_observed", "competition_summary_created", "market_pricing_computed", "market_intelligence_completed"}
    assert result["read_only"] is True


def test_competition_evidence_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.competition_evidence(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_competition_evidence_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/competition-evidence" in paths


def test_competition_summaries_route_returns_decoded_summaries(monkeypatch):
    fake_summaries = [{"run_id": "commerce-mvp-run-1", "observed_competitor_count": 2, "observed_median_price": 29.75}]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"competition_summaries": fake_summaries})
    result = canonical_events.competition_summaries(limit=100, offset=0, request=None)
    assert result["summaries"] == fake_summaries
    assert result["read_only"] is True


def test_competition_summaries_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.competition_summaries(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_competition_summaries_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/competition-summaries" in paths
