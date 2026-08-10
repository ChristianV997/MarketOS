"""Tests for the GET /api/events/opportunity-scoring read view — a thin
event_type filter over the existing timeline, no second query engine."""
from api.routes import canonical_events


def test_opportunity_scoring_route_filters_to_scoring_event_types(monkeypatch):
    fake_events = [
        {"event_type": "commerce_mvp_run_started", "payload_summary": {}},
        {"event_type": "opportunity_scoring_started", "payload_summary": {}},
        {"event_type": "candidate_scored", "payload_summary": {"candidate_id": "c1"}},
        {"event_type": "candidate_scored", "payload_summary": {"candidate_id": "c2"}},
        {"event_type": "opportunity_ranked", "payload_summary": {}},
        {"event_type": "opportunity_scoring_completed", "payload_summary": {}},
        {"event_type": "supplier_evidence_requested", "payload_summary": {}},
        {"event_type": "shopify_product_observed", "payload_summary": {}},
    ]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"timeline": {"events": fake_events}})
    result = canonical_events.opportunity_scoring(limit=100, offset=0, request=None)
    types = {event["event_type"] for event in result["events"]}
    assert types == {"opportunity_scoring_started", "candidate_scored", "opportunity_ranked", "opportunity_scoring_completed"}
    assert len(result["events"]) == 5
    assert result["read_only"] is True


def test_opportunity_scoring_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.opportunity_scoring(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_opportunity_scoring_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/opportunity-scoring" in paths


def test_opportunity_rankings_route_returns_decoded_summaries(monkeypatch):
    fake_rankings = [{"run_id": "commerce-mvp-run-1", "top_candidate_id": "c1", "scores": [{"candidate_id": "c1", "composite_score": 51.06}]}]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"opportunity_rankings": fake_rankings})
    result = canonical_events.opportunity_rankings(limit=100, offset=0, request=None)
    assert result["rankings"] == fake_rankings
    assert result["read_only"] is True


def test_opportunity_rankings_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.opportunity_rankings(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_opportunity_rankings_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/opportunity-rankings" in paths
