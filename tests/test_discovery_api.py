import json
from pathlib import Path

from fastapi.testclient import TestClient
from backend.api import app


OPPORTUNITY_FIXTURES = Path(__file__).parent / "fixtures" / "opportunity_discovery"


def _opportunity_fixture(name: str) -> dict:
    return json.loads((OPPORTUNITY_FIXTURES / name).read_text(encoding="utf-8"))


def _ready_opportunity_fixture() -> dict:
    payload = _opportunity_fixture("product_complete.json")
    assumptions = payload["candidates"][0]["economics"]["assumptions"]
    for key in (
        "affiliate_fee_rate",
        "brokerage_fee",
        "cac",
        "domestic_shipping",
        "international_shipping",
        "payment_fee_fixed",
        "platform_fee_fixed",
    ):
        assumptions[key] = {"amount": "0", "currency": "MXN"} if key != "affiliate_fee_rate" else "0"
    return payload


def test_discovery_api_fixture_and_cap():
    client = TestClient(app)
    path = str(Path(__file__).parent / "fixtures" / "market_evidence_seed.json")
    response = client.post("/api/discovery/market-discovery", json={"dataset_paths": [path], "run_validation_services": False})
    assert response.status_code == 200
    assert response.json()["discovery"]["category_opportunities"]
    blocked = client.post("/api/discovery/market-discovery", json={"dataset_paths": ["../outside"]})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"


def test_opportunity_discovery_api_preserves_missing_empty_and_nonempty_gaps():
    from services.opportunity_discovery import run_discovery

    client = TestClient(app)

    absent = client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate"},
        json={"candidates": []},
    )
    assert absent.status_code == 200
    assert absent.json()["status"] == "unavailable"
    assert absent.json()["decisions"] == []
    assert "evidence_gaps" not in absent.json()

    complete_payload = _ready_opportunity_fixture()
    complete = client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate"},
        json=complete_payload,
    )
    assert complete.status_code == 200
    complete_data = complete.json()
    assert complete_data["decisions"][0]["evidence_gaps"] == []

    incomplete_payload = _opportunity_fixture("product_complete.json")
    incomplete_payload["candidates"][0]["economics"]["assumptions"].pop("supplier_shipping")
    incomplete = client.post(
        "/api/discovery/opportunity-discovery",
        params={"mode": "evaluate"},
        json=incomplete_payload,
    )
    assert incomplete.status_code == 200
    incomplete_data = incomplete.json()
    assert "shipping" in incomplete_data["decisions"][0]["evidence_gaps"]

    assert complete_data == run_discovery("evaluate", complete_payload).to_dict()
    assert incomplete_data == run_discovery("evaluate", incomplete_payload).to_dict()
