"""Route regressions for dropship dashboard error disclosure.

Proves that exception text, filesystem paths, and secret-shaped values cannot
reach clients, while success payloads and documented error shapes remain
compatible (``status`` / ``error`` contract with stable codes).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import dropship_dashboard as dashboard


SECRET_MARKER = "sk_live_SYNTHETIC_SECRET_MUST_NOT_LEAK"
PATH_MARKER = "/var/secret/dropship_SYNTHETIC.json"
MESSAGE_MARKER = f"boom path={PATH_MARKER} token={SECRET_MARKER}"


class _SyntheticLeakError(RuntimeError):
    """Exception whose message carries path and secret-shaped markers."""


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(dashboard.router, prefix="/api/dropship")
    return TestClient(app)


def _assert_safe_error_payload(payload: dict, *, code: str, required_keys: set[str] | None = None) -> None:
    assert payload["status"] == "error"
    assert payload["error"] == code
    assert payload.get("error_type") == "_SyntheticLeakError"
    raw = json.dumps(payload)
    assert MESSAGE_MARKER not in raw
    assert SECRET_MARKER not in raw
    assert PATH_MARKER not in raw
    assert "Traceback" not in raw
    assert "File \"" not in raw
    if required_keys:
        assert required_keys.issubset(payload.keys())


def _raise_leak(*_args, **_kwargs):
    raise _SyntheticLeakError(MESSAGE_MARKER)


# (method, path, patch_target, expected_code, required_extra_keys)
ERROR_CASES = [
    ("GET", "/api/dropship/profitability", "backend.metrics.profitability.calculate_profitability", "profitability_failed", {"total_profit"}),
    ("GET", "/api/dropship/profitability/products", "backend.metrics.profitability.calculate_profitability", "profitability_products_failed", {"products"}),
    ("GET", "/api/dropship/profitability/product/widget", "backend.metrics.profitability.product_timeline", "product_timeline_failed", {"timeline"}),
    ("GET", "/api/dropship/forecast", "backend.metrics.profitability.revenue_forecast", "forecast_failed", set()),
    ("GET", "/api/dropship/costs/summary", "backend.cost_tracking.cost_report", "cost_summary_failed", {"total_spend"}),
    ("GET", "/api/dropship/costs/timeline", "backend.cost_tracking.cost_timeline", "cost_timeline_failed", {"data"}),
    ("GET", "/api/dropship/costs/by-service", "backend.cost_tracking.cost_report", "costs_by_service_failed", {"by_service"}),
    ("GET", "/api/dropship/errors/summary", "backend.error_telemetry.error_summary", "error_summary_failed", {"total_errors"}),
    ("GET", "/api/dropship/errors/recent", "backend.error_telemetry.error_details", "errors_recent_failed", {"errors"}),
    ("GET", "/api/dropship/metrics/ingest", "backend.metrics.campaign_metrics.ingest_campaign_metrics", "metrics_ingest_failed", set()),
    ("GET", "/api/dropship/metrics/performance", "backend.metrics.campaign_metrics.campaign_performance", "metrics_performance_failed", {"campaigns"}),
    ("GET", "/api/dropship/metrics/campaign/camp-1", "backend.metrics.campaign_metrics.campaign_by_id", "campaign_metrics_failed", set()),
    ("GET", "/api/dropship/optimization/scaling-decisions", "backend.optimization.budget_scaling.compute_scaling_decisions", "scaling_decisions_failed", {"decisions"}),
    ("GET", "/api/dropship/optimization/scaling-summary", "backend.optimization.budget_scaling.scaling_summary", "scaling_summary_failed", set()),
    ("GET", "/api/dropship/alerts", "backend.monitoring.alerts.alert_summary", "alerts_failed", {"alerts"}),
    ("POST", "/api/dropship/alerts/evaluate", "backend.monitoring.alerts.evaluate_alerts", "alerts_evaluate_failed", set()),
    ("GET", "/api/dropship/report?regenerate=true", "backend.reporting.weekly_report.generate_report", "report_failed", set()),
    ("GET", "/api/dropship/calibration", "backend.metrics.calibration_tuning.confidence_report", "calibration_failed", set()),
    ("GET", "/api/dropship/signal-cache", "backend.discovery.signal_cache.cache_status", "signal_cache_failed", set()),
]


@pytest.mark.parametrize(("method", "path", "target", "code", "extras"), ERROR_CASES)
def test_error_paths_never_disclose_exception_details(method, path, target, code, extras):
    client = _client()
    with patch(target, side_effect=_raise_leak):
        if method == "GET":
            response = client.get(path)
        else:
            response = client.post(path)
    assert response.status_code == 200
    _assert_safe_error_payload(response.json(), code=code, required_keys=extras)


def test_summary_corrupt_snapshot_returns_stable_code(tmp_path, monkeypatch):
    snap = tmp_path / "dropship.json"
    snap.write_text("{not-json", encoding="utf8")
    monkeypatch.setattr(dashboard, "_DROPSHIP_SNAPSHOT_PATH", snap)
    response = _client().get("/api/dropship/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"] == "snapshot_load_failed"
    assert payload["error_type"] in {"JSONDecodeError", "ValueError"}
    raw = json.dumps(payload)
    assert "not-json" not in raw
    assert str(snap) not in raw


def test_summary_missing_snapshot_preserves_documented_empty_contract(tmp_path, monkeypatch):
    missing = tmp_path / "absent-dropship.json"
    monkeypatch.setattr(dashboard, "_DROPSHIP_SNAPSHOT_PATH", missing)
    response = _client().get("/api/dropship/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "no_cycles_yet"
    assert payload["discovered"] == 0
    assert payload["launches"] == []


def test_summary_valid_snapshot_returns_payload(tmp_path, monkeypatch):
    snap = tmp_path / "dropship.json"
    body = {"status": "ok", "discovered": 2, "validated": 1, "green": 1, "launched": 1, "launches": [{"product": "widget"}]}
    snap.write_text(json.dumps(body), encoding="utf8")
    monkeypatch.setattr(dashboard, "_DROPSHIP_SNAPSHOT_PATH", snap)
    response = _client().get("/api/dropship/summary")
    assert response.status_code == 200
    assert response.json()["launches"][0]["product"] == "widget"


def test_campaigns_valid_snapshot_success_shape(tmp_path, monkeypatch):
    snap = tmp_path / "dropship.json"
    snap.write_text(
        json.dumps(
            {
                "launches": [
                    {
                        "product": "widget",
                        "confidence": 0.7,
                        "predicted_roas": 1.5,
                        "campaigns": [
                            {
                                "campaign_id": "c1",
                                "platform": "meta",
                                "status": "active",
                                "budget": 10,
                                "hook": "h",
                                "angle": "a",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf8",
    )
    monkeypatch.setattr(dashboard, "_DROPSHIP_SNAPSHOT_PATH", snap)
    response = _client().get("/api/dropship/campaigns")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["campaigns"][0]["campaign_id"] == "c1"
    assert "last_updated" in payload


def test_campaigns_corrupt_snapshot_degrades_to_empty_success(tmp_path, monkeypatch):
    """Campaigns historically swallow load failures and return an empty list."""
    snap = tmp_path / "dropship.json"
    snap.write_text("{broken", encoding="utf8")
    monkeypatch.setattr(dashboard, "_DROPSHIP_SNAPSHOT_PATH", snap)
    response = _client().get("/api/dropship/campaigns")
    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 0
    assert payload["campaigns"] == []
    raw = json.dumps(payload)
    assert "broken" not in raw
    assert SECRET_MARKER not in raw


def test_discovery_sources_error_is_stable():
    client = _client()

    class _BoomRegistry:
        def status_report(self):
            raise _SyntheticLeakError(MESSAGE_MARKER)

    with patch("backend.discovery.registry.discovery_registry", _BoomRegistry()):
        response = client.get("/api/dropship/discovery/sources")
    assert response.status_code == 200
    _assert_safe_error_payload(response.json(), code="discovery_sources_failed")


def test_campaign_not_found_contract_preserved():
    with patch("backend.metrics.campaign_metrics.campaign_by_id", return_value=None):
        response = _client().get("/api/dropship/metrics/campaign/missing-id")
    assert response.status_code == 200
    assert response.json() == {"status": "not_found", "campaign_id": "missing-id"}


def test_status_and_config_success_contracts():
    client = _client()
    status = client.get("/api/dropship/status")
    assert status.status_code == 200
    assert status.json()["status"] == "ok"
    assert "services" in status.json()

    services = client.get("/api/dropship/config/services")
    assert services.status_code == 200
    assert services.json()["status"] == "ok"
    assert "services" in services.json()

    needed = client.get("/api/dropship/config/credentials-needed")
    assert needed.status_code == 200
    assert needed.json()["status"] in {"ok", "setup_required"}
    assert "missing_credentials" in needed.json()


def test_safe_error_helper_never_embeds_exception_text():
    exc = _SyntheticLeakError(MESSAGE_MARKER)
    payload = dashboard._safe_error("unit_failed", exc=exc, extras={"items": []})
    assert payload == {
        "status": "error",
        "error": "unit_failed",
        "items": [],
        "error_type": "_SyntheticLeakError",
    }
    assert MESSAGE_MARKER not in json.dumps(payload)


def test_log_failure_omits_exception_message(caplog):
    import logging

    with caplog.at_level(logging.ERROR, logger=dashboard._log.name):
        dashboard._log_failure("unit_op", _SyntheticLeakError(MESSAGE_MARKER))
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "unit_op failed error_type=_SyntheticLeakError" in joined
    assert MESSAGE_MARKER not in joined
    assert SECRET_MARKER not in joined
    assert PATH_MARKER not in joined


def test_module_has_no_str_exc_client_sinks():
    source = Path(dashboard.__file__).read_text(encoding="utf8")
    assert 'str(exc)' not in source
    assert "format_exc" not in source
    assert "traceback" not in source
