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


class TestEcommerceOperatorRoute:
    def test_returns_readiness_contribution_decision(self, client):
        resp = client.post(
            "/api/services/ecommerce-operator",
            params={"product": "Widget", "roas": 2.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "readiness" in data
        assert "contribution" in data
        assert "decision" in data
        assert data["experiment_id"]

    def test_dict_body_fields_populate_readiness_checklist(self, client):
        resp = client.post(
            "/api/services/ecommerce-operator",
            params={"product": "Widget", "roas": 2.0, "budget_ceiling": 500.0},
            json={
                "validation": {"verdict": "green"},
                "unit_economics": {"net_margin_pct": 20},
                "kill_criteria": {"min_roas": 1.5},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["readiness"]["checklist"]["has_product_validation"] is True
        assert data["readiness"]["checklist"]["has_margin_analysis"] is True


class TestCreativeGrowthRoute:
    def test_returns_result_no_infinity_leak(self, client):
        resp = client.post("/api/services/creative-growth", params={"product": "Widget"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["product_name"] == "Widget"
        assert data["experiment_id"]


class TestCustomerIntelligenceRoute:
    def test_returns_result_with_vertical(self, client):
        resp = client.post(
            "/api/services/customer-intelligence",
            params={"business_type": "clinic", "vertical": "clinic_wellness"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["vertical"] == "clinic_wellness"
        assert data["result"]["vertical_playbook"] is not None


class TestDigitalProductRoute:
    def test_returns_margin_and_validation(self, client):
        resp = client.post(
            "/api/services/digital-product",
            params={"offer_name": "Playbook", "price": 99.0, "target_buyers": 5, "has_existing_audience": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["margin"]
        assert data["result"]["validation"]["verdict"] == "strong"


class TestSalesAutomationRoute:
    def test_returns_session_and_handoff(self, client):
        resp = client.post("/api/services/sales-automation", params={"vertical": "car_sales"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session"]
        assert data["handoff"]
        assert data["experiment_id"]


class TestProfitStackAdvisorRoute:
    def test_returns_result_and_experiment_id(self, client):
        resp = client.post(
            "/api/services/profit-stack-advisor",
            params={"business_name": "Own Store", "business_model": "own_ecommerce"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["recommendation"]["commerce_provider_recommendation"]["provider_id"] == "woocommerce"
        assert data["experiment_id"]

    def test_missing_required_param_returns_422(self, client):
        resp = client.post("/api/services/profit-stack-advisor")
        assert resp.status_code == 422


class TestServicesRouteNeverRaises:
    def test_unexpected_failure_returns_error_dict_not_500(self, client, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("unexpected")
        monkeypatch.setattr("services.product_research.audit.run_product_audit", _boom)
        resp = client.post("/api/services/product-audit", params={"product": "Widget"})
        assert resp.status_code == 200  # the route itself never 500s
        assert "error" in resp.json()
