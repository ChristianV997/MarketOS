from backend.execution_cockpit import executor
from backend.execution_cockpit.cockpit_registry import CockpitRegistry
from backend.execution_cockpit.cockpit_models import CockpitAction


def test_plan_preview_and_pending_approval(monkeypatch, tmp_path):
    cockpit = CockpitRegistry(tmp_path / "cockpit.json"); monkeypatch.setattr(executor, "get_cockpit_registry", lambda: cockpit)
    monkeypatch.setattr(executor, "resolve_plan_to_cockpit_actions", lambda plan_id: [CockpitAction("a", "default", "generate_optimization", "Optimize", "simulate", source_plan_id=plan_id, safe_payload={"workspace_id": "default"})])
    preview = executor.preview_cockpit_plan("p")
    assert preview["executable_count"] == 1
    result = executor.execute_cockpit_plan("p")
    assert result["status"] == "pending_approval"
    assert result["pending_approvals"]
