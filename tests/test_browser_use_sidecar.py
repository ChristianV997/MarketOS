from fastapi.testclient import TestClient

from backend.sidecars import browser_use_api


def test_browser_use_sidecar_rejects_unauthenticated_execution(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_WORKER_TOKEN", "worker-secret")
    client = TestClient(browser_use_api.app)
    response = client.post("/execute", json={"workflow": "supplier_research"})
    assert response.status_code == 401


def test_browser_use_sidecar_handles_dry_run_without_launching_browser(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_WORKER_TOKEN", "worker-secret")
    client = TestClient(browser_use_api.app)
    response = client.post(
        "/execute",
        headers={"Authorization": "Bearer worker-secret"},
        json={"workflow": "supplier_research", "payload": {"query": "travel mug"}, "context": {"dry_run": True}},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "planned"


def test_browser_use_sidecar_requires_approved_context_for_live_work(monkeypatch):
    monkeypatch.setenv("BROWSER_USE_WORKER_TOKEN", "worker-secret")
    monkeypatch.setenv("BROWSER_USE_ALLOWED_DOMAINS", "supplier.example")
    client = TestClient(browser_use_api.app)
    response = client.post(
        "/execute",
        headers={"Authorization": "Bearer worker-secret"},
        json={
            "workflow": "supplier_research",
            "payload": {"url": "https://supplier.example/product"},
            "context": {"dry_run": False, "idempotency_key": "research-1"},
        },
    )
    assert response.status_code == 403
    assert "approval" in response.json()["detail"]
