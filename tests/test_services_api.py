"""Tests for api.routes.services — thin route wrappers over
services.product_research/services.unit_economics (Phase 7)."""
import backend.core.persistence as pers
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.services import router


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", lambda force_refresh=False: [])


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestProductAuditRoute:
    def test_returns_result_and_experiment_id(self, client):
        resp = client.post("/api/services/product-audit", params={"product": "Widget"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["product_name"] == "Widget"
        assert data["experiment_id"]

    def test_missing_required_param_returns_422(self, client):
        resp = client.post("/api/services/product-audit")
        assert resp.status_code == 422


class TestUnitEconomicsRoute:
    def test_returns_break_even_fields(self, client):
        resp = client.post(
            "/api/services/unit-economics",
            params={"product": "Widget", "cost": 10.0, "price": 40.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "break_even_cac" in data["result"]
        assert "required_roas" in data["result"]

    def test_geo_param_populates_geo_margin(self, client):
        resp = client.post(
            "/api/services/unit-economics",
            params={"product": "Widget", "cost": 10.0, "price": 40.0, "geo": "MX"},
        )
        assert resp.json()["result"]["geo_margin"] is not None


class TestServicesRouteNeverRaises:
    def test_unexpected_failure_returns_error_dict_not_500(self, client, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("unexpected")
        monkeypatch.setattr("services.product_research.audit.run_product_audit", _boom)
        resp = client.post("/api/services/product-audit", params={"product": "Widget"})
        assert resp.status_code == 200  # the route itself never 500s
        assert "error" in resp.json()
