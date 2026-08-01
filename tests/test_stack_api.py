"""Tests for api.routes.stack — the lightweight, non-billable stack-recommend endpoint."""
import backend.core.persistence as pers
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.stack import router


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestStackRecommendRoute:
    def test_returns_woocommerce_recommendation_by_default(self, client):
        resp = client.post("/api/stack/recommend", params={"business_model": "own_ecommerce"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["commerce_provider_recommendation"]["provider_id"] == "woocommerce"
        assert data["result"]["status"] == "recommended"

    def test_never_raises_on_unexpected_failure(self, client, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("boom")
        monkeypatch.setattr("backend.stack_planner.planner.recommend_stack", _boom)
        resp = client.post("/api/stack/recommend", params={"business_model": "own_ecommerce"})
        assert resp.status_code == 200
        assert "error" in resp.json()
