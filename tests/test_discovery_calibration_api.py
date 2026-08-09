from fastapi.testclient import TestClient
from backend.api import app


def test_calibration_api_handles_insufficient_data():
    client = TestClient(app)
    response = client.post("/api/discovery/source-calibration", json={"workspace_id": "api-calibration-empty"})
    assert response.status_code == 200 and response.json()["status"] in {"partial", "completed"}
    assert client.get("/api/discovery/source-calibrations", params={"limit": 1}).status_code == 200
    assert client.get("/api/discovery/source-calibration/profiles", params={"limit": 1}).status_code == 200
    assert client.get("/api/discovery/source-calibration/signals", params={"limit": 1}).status_code == 200
