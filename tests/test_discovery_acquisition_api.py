from fastapi.testclient import TestClient
from backend.api import app


def test_playbooks_and_stubs_api():
    client = TestClient(app)
    assert client.get("/api/discovery/source-playbooks").json()["source_playbooks"]
    assert client.get("/api/discovery/source-playbooks/supplier_catalog_csv").json()["source_playbook"]["parser_type"] == "supplier_catalog_csv"
    assert client.get("/api/discovery/connector-stubs").json()["connector_stubs"]
    assert client.get("/api/discovery/connector-stubs/supplier_catalog_export_connector").json()["connector_stub"]["status"] == "disabled"


def test_acquisition_plan_status_validation():
    client = TestClient(app)
    response = client.post("/api/discovery/acquisition-plans/unknown/status", json={"status": "live"})
    assert response.json()["status"] == "not_found"
