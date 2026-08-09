from pathlib import Path
from fastapi.testclient import TestClient
from backend.api import app


def test_discovery_api_fixture_and_cap():
    client = TestClient(app)
    path = str(Path(__file__).parent / "fixtures" / "market_evidence_seed.json")
    response = client.post("/api/discovery/market-discovery", json={"dataset_paths": [path], "run_validation_services": False})
    assert response.status_code == 200
    assert response.json()["discovery"]["category_opportunities"]
    blocked = client.post("/api/discovery/market-discovery", json={"dataset_paths": ["../outside"]})
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"
