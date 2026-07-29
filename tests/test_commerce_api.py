"""Safety checks for the commerce-cycle API boundary."""
from unittest.mock import MagicMock, patch
import asyncio
import json
from pathlib import Path
import pytest


def test_live_commerce_api_requires_explicit_confirmation():
    from backend.api import commerce_cycle

    with patch("backend.commerce.run_commerce_cycle") as run:
        response = commerce_cycle({"dry_run": False})

    assert response["launchable"] is False
    assert "live_execution_requires_confirm_live" in response["reasons"]
    run.assert_not_called()


def test_commerce_api_passes_confirmed_live_mode_to_loop():
    from backend.api import commerce_cycle

    report = MagicMock()
    report.to_dict.return_value = {"cycle": "confirmed"}
    with patch("backend.commerce.run_commerce_cycle", return_value=report) as run:
        response = commerce_cycle({"dry_run": False, "confirm_live": True})

    assert response == {"cycle": "confirmed"}
    assert run.call_args.kwargs["dry_run"] is False


def test_string_false_is_parsed_as_live_and_still_requires_confirmation():
    from backend.api import commerce_cycle

    with patch("backend.commerce.run_commerce_cycle") as run:
        response = commerce_cycle({"dry_run": "false"})

    assert "live_execution_requires_confirm_live" in response["reasons"]
    run.assert_not_called()


def test_lifespan_starts_and_stops_runtime_services(monkeypatch):
    import backend.api as api

    events: list[str] = []

    class Thread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            events.append("thread")

    monkeypatch.setattr(api.threading, "Thread", Thread)
    monkeypatch.setattr("backend.core.serializer.load", lambda path: None)
    monkeypatch.setattr("backend.core.serializer.save", lambda state, path: events.append("save"))
    monkeypatch.setattr(api, "_start_runtime_services", lambda: events.append("start_services"))
    monkeypatch.setattr(api, "_stop_runtime_services", lambda: events.append("stop_services"))

    async def exercise():
        async with api._lifespan(api.app):
            assert api._bg_running is True
            assert events.count("thread") == 2
            assert "start_services" in events
        assert api._bg_running is False

    asyncio.run(exercise())
    assert events[-2:] == ["stop_services", "save"]


def test_readiness_distinguishes_health_from_runtime_startup(monkeypatch):
    import backend.api as api
    from fastapi.testclient import TestClient

    monkeypatch.setattr("backend.core.serializer.load", lambda _path: None)
    monkeypatch.setattr("backend.core.serializer.save", lambda *_args: None)
    monkeypatch.setattr(api, "_start_runtime_services", lambda: None)
    monkeypatch.setattr(api, "_stop_runtime_services", lambda: None)

    api._bg_running = False
    api._runtime_services_ready = False
    assert api.ready().status_code == 503
    assert api.health() == {"ok": True}

    with TestClient(api.app) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"ready": True}


def test_signal_metrics_endpoint_exposes_cache_telemetry():
    from backend.api import signal_metrics
    result = signal_metrics()
    assert "cache_hit_rate" in result
    assert "last_refresh_duration_s" in result
    assert "source_failures" in result


def test_prometheus_exposes_signal_cache_metric_families():
    pytest.importorskip("prometheus_client")
    from backend.api import prometheus_metrics
    from core.signals import SignalEngine

    engine = SignalEngine()
    engine.register_source("prometheus-test", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    engine.get(force_refresh=True)
    engine.get()
    payload = prometheus_metrics().body.decode("utf-8")
    assert "marketos_signal_cache_hits_total" in payload
    assert "marketos_signal_cache_refreshes_total" in payload
    assert "marketos_signal_cache_refresh_duration_seconds" in payload
    assert "marketos_signal_cache_last_refresh_duration_seconds" in payload
    assert "marketos_signal_source_failures_total" in payload


def test_api_deployment_smoke_runs_dry_commerce_cycle(monkeypatch):
    """Exercise the public HTTP surface through startup, execution, and shutdown.

    Runtime workers are replaced with inert threads so this remains a true
    application-lifespan test without creating background commerce activity.
    """
    from fastapi.testclient import TestClient
    import backend.api as api

    class InertThread:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def start(self):
            return None

    fixture_dir = Path(__file__).parent / "fixtures"
    payload = {
        "signals": json.loads((fixture_dir / "commerce_signals.json").read_text()),
        "products": json.loads((fixture_dir / "commerce_products.json").read_text()),
        "offers": json.loads((fixture_dir / "commerce_offers.json").read_text()),
        "top_k": 1,
        "budget": 25,
    }

    monkeypatch.setattr(api.threading, "Thread", InertThread)
    monkeypatch.setattr("backend.core.serializer.load", lambda _path: None)
    monkeypatch.setattr("backend.core.serializer.save", lambda *_args: None)
    monkeypatch.setattr(api, "_start_runtime_services", lambda: None)
    monkeypatch.setattr(api, "_stop_runtime_services", lambda: None)

    with TestClient(api.app) as client:
        health = client.get("/health")
        response = client.post("/commerce/cycle", json=payload)

    assert health.status_code == 200
    assert health.json() == {"ok": True}
    assert response.status_code == 200
    result = response.json()
    assert result["dry_run"] is True
    assert result["summary"] == {
        "signals_collected": 1,
        "ranked": 1,
        "creatives": 1,
        "launches": 1,
        "outcomes": 1,
        "feedback_records": 1,
        "launchable": 1,
    }
