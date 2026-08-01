"""Monitoring configuration invariants for signal health observability."""
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_prometheus_rules_cover_signal_health_alerts():
    rules = (ROOT / "monitoring" / "prometheus_rules.yml").read_text(encoding="utf-8")
    assert "MarketOSSignalRefreshLatencyHigh" in rules
    assert "MarketOSSignalCacheHitRateLow" in rules
    assert "MarketOSSignalSourceFailuresRepeated" in rules
    assert "MarketOSSignalSourceRefreshLatencyHigh" in rules
    assert "MarketOSSignalSourceFailureRateHigh" in rules
    assert "MarketOSOSSProviderFailuresRepeated" in rules
    assert "MarketOSOSSProviderRefreshLatencyHigh" in rules
    assert "MarketOSWebhookFailuresRepeated" in rules
    assert "marketos_signal_cache_lookups_total" in rules


def test_grafana_dashboard_has_signal_health_panels():
    dashboard = json.loads((ROOT / "monitoring" / "grafana" / "dashboards" / "marketos-signal-health.json").read_text(encoding="utf-8"))
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Signal Cache Hit Rate" in titles
    assert "Signal Refresh Latency (p95)" in titles
    assert "Source Failures by Source" in titles
    assert "Source Refresh Latency (p95)" in titles
    assert "Source Success and Failure Rate" in titles


def test_compose_mounts_monitoring_provisioning():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "monitoring/prometheus_rules.yml:/etc/prometheus/marketos-rules.yml:ro" in compose
    assert "monitoring/grafana/provisioning:/etc/grafana/provisioning:ro" in compose
