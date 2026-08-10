"""Tests for the GET /api/events/supplier-evidence read view — a thin
event_type filter over the existing timeline, no second query engine."""
from api.routes import canonical_events


def test_supplier_evidence_route_filters_to_supplier_event_types(monkeypatch):
    fake_events = [
        {"event_type": "commerce_mvp_run_started", "payload_summary": {}},
        {"event_type": "supplier_evidence_requested", "payload_summary": {}},
        {"event_type": "supplier_product_observed", "payload_summary": {"title": "Widget"}},
        {"event_type": "commerce_economics_enriched", "payload_summary": {}},
        {"event_type": "supplier_evidence_degraded", "payload_summary": {}},
        {"event_type": "shopify_product_observed", "payload_summary": {}},
    ]
    monkeypatch.setattr(canonical_events, "_report", lambda source, query: {"timeline": {"events": fake_events}})
    result = canonical_events.supplier_evidence(limit=100, offset=0, request=None)
    types = {event["event_type"] for event in result["events"]}
    assert types == {"supplier_evidence_requested", "supplier_product_observed", "commerce_economics_enriched", "supplier_evidence_degraded"}
    assert result["read_only"] is True


def test_supplier_evidence_route_respects_rate_limit(monkeypatch):
    from backend.security.rate_limit import RateLimitResult

    monkeypatch.setattr(
        canonical_events, "check_rate_limit",
        lambda policy, key: RateLimitResult(allowed=False, policy="event_read", limit=1, remaining=0, retry_after_seconds=5),
    )
    response = canonical_events.supplier_evidence(limit=100, offset=0, request=None)
    assert response.status_code == 429


def test_router_exposes_supplier_evidence_get_route():
    paths = {route.path for route in canonical_events.router.routes}
    assert "/api/events/supplier-evidence" in paths
