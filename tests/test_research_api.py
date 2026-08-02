"""Read-only API coverage for market-research operational surfaces."""
import os
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.research import router
from backend.research import TrendRecordStore


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("RESEARCH_DB_PATH", str(tmp_path / "research.db"))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_opportunities_and_source_summary_routes(client, monkeypatch):
    db_path = os.environ["RESEARCH_DB_PATH"]
    store = TrendRecordStore(path=db_path)
    timestamp = datetime.now(timezone.utc).isoformat()
    for source in ("reddit", "mercadolibre"):
        store.upsert({
            "topic": "Wireless Earbuds",
            "intent": "buy",
            "velocity": 0.7,
            "competition": None,
            "source": source,
            "freshness_ts": timestamp,
            "confidence": 0.7,
            "raw": {"fixture": source},
        })

    opportunity_response = client.get("/research/opportunities", params={"min_sources": 2})
    source_response = client.get("/research/sources")

    assert opportunity_response.status_code == 200
    assert opportunity_response.json()["opportunities"][0]["source_count"] == 2
    assert source_response.status_code == 200
    assert {item["source"] for item in source_response.json()["sources"]} == {"reddit", "mercadolibre"}


def test_opportunity_route_rejects_unknown_intent(client):
    response = client.get("/research/opportunities", params={"intent": "invalid"})
    assert response.status_code == 422


def test_intelligence_input_uses_ranked_deduplicated_opportunities(monkeypatch, tmp_path):
    from backend.api import _research_intelligence_keywords

    store = TrendRecordStore(path=str(tmp_path / "research.db"))
    timestamp = datetime.now(timezone.utc).isoformat()
    for source in ("reddit", "mercadolibre"):
        store.upsert({
            "topic": "Wireless Earbuds" if source == "reddit" else "wireless earbuds!",
            "intent": "buy",
            "velocity": 0.7,
            "competition": None,
            "source": source,
            "freshness_ts": timestamp,
            "confidence": 0.7,
            "raw": {"fixture": source},
        })
    store.upsert({
        "topic": "single-source item",
        "intent": "buy",
        "velocity": 1.0,
        "competition": None,
        "source": "youtube",
        "freshness_ts": timestamp,
        "confidence": 1.0,
        "raw": {"fixture": "youtube"},
    })
    monkeypatch.setenv("RESEARCH_INTELLIGENCE_MIN_SOURCES", "2")
    monkeypatch.setenv("RESEARCH_INTELLIGENCE_MAX_TOPICS", "5")

    assert _research_intelligence_keywords(store) == ["Wireless Earbuds"]
