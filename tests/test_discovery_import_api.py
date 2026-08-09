from pathlib import Path
from fastapi.testclient import TestClient
from backend.api import app


def test_import_api():
    client = TestClient(app)
    path = str(Path(__file__).parent / "fixtures" / "evidence_imports" / "supplier_catalog_sample.csv")
    response = client.post("/api/discovery/import-evidence", json={"input_path": path, "parser_type": "supplier_catalog_csv", "source_name": "supplier"})
    assert response.status_code == 200 and response.json()["import_job"]["status"] == "completed"
    assert client.get("/api/discovery/source-quality").status_code == 200
    blocked = client.post("/api/discovery/import-evidence", json={"input_path": path, "parser_type": "unknown"})
    assert blocked.json()["status"] == "blocked"
