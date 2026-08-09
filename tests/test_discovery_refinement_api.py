from fastapi.testclient import TestClient
from backend.api import app


def test_refinement_endpoints():
    client = TestClient(app)
    response = client.post("/api/discovery/refinement-cycle", json={"create_templates": False})
    assert response.status_code == 200 and response.json()["gap_analysis"]
    assert client.get("/api/discovery/gap-analyses").status_code == 200
    assert client.get("/api/discovery/import-plans").status_code == 200
    assert client.get("/api/discovery/comparisons").status_code == 200


def test_refinement_import_limit():
    client = TestClient(app)
    response = client.post("/api/discovery/import-refine-compare", json={"imports": [{}] * 11})
    assert response.json()["status"] == "blocked"
