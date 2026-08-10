from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.security.request_context import RequestContextMiddleware


def test_request_context_adds_safe_correlation_headers():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/api/events/timeline")
    def timeline():
        return {"read_only": True}

    with TestClient(app) as client:
        response = client.get("/api/events/timeline", headers={"X-Request-ID": "operator-123"})
    assert response.headers["x-request-id"] == "operator-123"
    assert response.headers["x-marketos-mvp-mode"] == "true"
    assert response.headers["x-marketos-read-only"] == "true"


def test_unsafe_request_id_is_replaced():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/health")
    def health():
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/health", headers={"X-Request-ID": "x\r\nset-cookie:bad"})
    assert response.headers["x-request-id"] != "x"
    assert len(response.headers["x-request-id"]) == 32
