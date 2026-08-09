def test_commercial_intelligence_routes_are_exposed():
    from backend.api import app
    paths=set(app.openapi().get("paths",{}))
    assert "/api/commercial-intelligence/market/analyze" in paths
    assert "/api/commercial-intelligence/cycle" in paths
