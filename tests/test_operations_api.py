from fastapi.testclient import TestClient


def test_operations_routes_are_mounted():
    from backend.api import app
    paths = set(app.openapi().get("paths", {}))
    assert "/api/operations/plans" in paths
    assert "/api/operations/calendars/{calendar_id}/ics" in paths
