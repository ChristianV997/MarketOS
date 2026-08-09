from backend.api import app
from api.routes.workflows import run as run_endpoint
from api.routes.workflows import runbook as runbook_endpoint


def test_workflow_routes_are_mounted_and_safe():
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    for included in app.routes:
        paths.update(getattr(route, "path", "") for route in getattr(getattr(included, "router", None), "routes", []))
        paths.update(getattr(route, "path", "") for route in getattr(getattr(included, "original_router", None), "routes", []))
    assert "/api/workflows/run" in paths
    assert "/api/workflows/{workflow_id}/resume" in paths
    result = run_endpoint({"workspace_id": "workflow-api-test", "workflow_type": "import_discovery_cycle", "payload": {"live": True}})
    assert result["status"] == "blocked"
    assert runbook_endpoint("executive_intelligence_cycle")["runbook"]["workflow_type"] == "executive_intelligence_cycle"
