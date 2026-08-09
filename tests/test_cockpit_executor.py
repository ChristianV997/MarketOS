from backend.execution_cockpit import executor
from backend.execution_cockpit.approval import create_pending_approval, decide_approval
from backend.execution_cockpit import approval
from backend.execution_cockpit.cockpit_models import CockpitAction
from backend.execution_cockpit.cockpit_registry import CockpitRegistry


def test_dry_run_and_approved_execution_create_checkpoints(monkeypatch, tmp_path):
    registry = CockpitRegistry(tmp_path / "cockpit.json"); monkeypatch.setattr(executor, "get_cockpit_registry", lambda: registry); monkeypatch.setattr(approval, "get_cockpit_registry", lambda: registry)
    action = CockpitAction("a", "default", "generate_optimization", "Optimize", "simulate", safe_payload={"workspace_id": "default"}); registry.register_action(action)
    pending = create_pending_approval(action); decide_approval(pending.approval_id, "approved", "ok")
    preview = executor.execute_cockpit_action("a", pending.approval_id, dry_run=True)
    assert preview["dry_run"] and preview["execution"]["output_summary"]["target_not_called"]
    assert len(registry.list_checkpoints(execution_id=preview["execution"]["execution_id"])) >= 2
    monkeypatch.setattr(executor, "_dispatch", lambda action, payload: {"optimization_id": "op1"})
    result = executor.execute_cockpit_action("a", pending.approval_id)
    assert result["status"] == "completed"
    assert result["execution"]["produced_object_ids"][0]["object_id"] == "op1"
