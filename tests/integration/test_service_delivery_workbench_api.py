from __future__ import annotations

import json

from api.routes import service_delivery_workbench as module


def test_workbench_is_safe_and_unavailable_without_projection(monkeypatch):
    monkeypatch.delenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", raising=False)
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["engagements"] == []


def test_workbench_rejects_projection_outside_artifacts(monkeypatch, tmp_path):
    path = tmp_path / "projection.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert report["diagnostics"] == ["service_delivery_projection_not_configured"]


def test_workbench_accepts_safe_read_only_projection(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "service_projection.json"
    path.write_text(json.dumps({"schema_version": "service-engagement-projection-v1", "availability": "manual_import", "generated_at": "deterministic", "read_only": True, "network_calls": False, "mutated": False, "engagements": []}), encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "available_read_only"
    assert report["live_endpoint"] == "/api/service-delivery/workbench"
    assert "read_only_artifact_projection" in report["diagnostics"]


def test_workbench_rejects_internal_fields(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "unsafe.json"
    path.write_text(json.dumps({"schema_version": "service-engagement-projection-v1", "read_only": True, "network_calls": False, "mutated": False, "engagements": [], "internal_prompt": "do not export"}), encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "internal_prompt" not in str(report)


def test_workbench_route_is_registered():
    from backend.api import app
    paths = set()
    for route in app.routes:
        if getattr(route, "path", None):
            paths.add(route.path)
        original = getattr(route, "original_router", None)
        paths.update(item.path for item in getattr(original, "routes", ()) if getattr(item, "path", None))
    assert "/api/service-delivery/workbench" in paths
