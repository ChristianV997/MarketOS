"""Tests for GET /api/events/research-portfolio and
/api/events/product-research — decoded summary + thin filter views,
following the same pattern as the opportunity-scoring/competition-evidence
read routes."""
import os

from api.routes import canonical_events


def test_product_research_route_filters_to_research_event_types(monkeypatch):
    fake_events = [
        {"event_type": "commerce_mvp_run_started", "payload_summary": {}},
        {"event_type": "candidate_discovered", "payload_summary": {}},
        {"event_type": "candidate_clustered", "payload_summary": {}},
        {"event_type": "research_portfolio_updated", "payload_summary": {}},
        {"event_type": "ranking_changed", "payload_summary": {}},
        {"event_type": "research_completed", "payload_summary": {}},
        {"event_type": "opportunity_scoring_started", "payload_summary": {}},
        {"event_type": "shopify_product_observed", "payload_summary": {}},
    ]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"timeline": {"events": fake_events}})
    result = canonical_events.product_research(limit=100, offset=0, request=None)
    types = {event["event_type"] for event in result["events"]}
    assert types == {"candidate_discovered", "candidate_clustered", "research_portfolio_updated", "ranking_changed", "research_completed"}
    assert result["read_only"] is True


def test_product_research_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.product_research(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_product_research_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/product-research" in paths


def test_research_portfolio_route_returns_decoded_summaries(monkeypatch):
    fake_portfolios = [{"run_id": "commerce-mvp-run-1", "top_candidate_id": "c1", "candidate_count": 2}]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"research_portfolios": fake_portfolios})
    result = canonical_events.research_portfolio(limit=100, offset=0, request=None)
    assert result["portfolios"] == fake_portfolios
    assert result["read_only"] is True


def test_research_portfolio_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.research_portfolio(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_research_portfolio_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/research-portfolio" in paths


def test_unconfigured_jsonl_path_never_key_errors_on_any_summary_route(monkeypatch):
    # Regression guard: _jsonl_report()'s unconfigured-path fallback must
    # carry every summary key every /api/events/* route reads, including
    # the ones added before this contribution (opportunity_rankings,
    # competition_summaries) and this contribution's own
    # (research_portfolios) -- a missing key here is a real KeyError at
    # request time, not just a cosmetic gap.
    monkeypatch.delenv("MARKETOS_EVENT_READ_JSONL_PATH", raising=False)
    assert canonical_events.opportunity_rankings(limit=100, offset=0, request=None)["rankings"] == []
    assert canonical_events.competition_summaries(limit=100, offset=0, request=None)["summaries"] == []
    assert canonical_events.research_portfolio(limit=100, offset=0, request=None)["portfolios"] == []
