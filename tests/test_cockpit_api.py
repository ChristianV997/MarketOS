def test_cockpit_routes_are_exposed():
    from backend.api import app
    paths = set(app.openapi().get("paths", {}))
    assert "/api/cockpit/actions/{action_id}/execute" in paths
    assert "/api/cockpit/plans/{plan_id}/preview" in paths
