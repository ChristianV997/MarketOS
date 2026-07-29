"""Tests for the /metrics/prometheus scrape endpoint (backend/api.py).

Regression guard for the Tier 3 gap: marketos_cycles_total/marketos_capital_usd/
etc. were being updated on every cycle but nothing ever exposed them over HTTP
for a real Prometheus server to scrape.
"""
from fastapi.testclient import TestClient

from backend.api import app


def test_prometheus_metrics_endpoint_exposes_text_format():
    client = TestClient(app)
    resp = client.get("/metrics/prometheus")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_prometheus_metrics_endpoint_includes_marketos_metrics():
    client = TestClient(app)
    resp = client.get("/metrics/prometheus")
    # Counters/gauges are always registered at import time even before any
    # cycle has run (default value 0), so the metric names themselves must
    # always appear in the exposition text.
    assert "marketos_cycles_total" in resp.text
    assert "marketos_capital_usd" in resp.text


def test_metrics_json_route_unaffected():
    """The pre-existing JSON dashboard-metrics route at the bare /metrics
    path must still work — the Prometheus scrape endpoint was deliberately
    mounted at the distinct /metrics/prometheus path to avoid colliding
    with it."""
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "content-type" in resp.headers
    assert "text/plain" not in resp.headers["content-type"]
