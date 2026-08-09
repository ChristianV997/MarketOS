import pytest
from backend.execution_cockpit import approval
from backend.execution_cockpit.cockpit_models import CockpitAction
from backend.execution_cockpit.cockpit_registry import CockpitRegistry


def test_approval_lifecycle_and_blocked_refusal(monkeypatch, tmp_path):
    registry = CockpitRegistry(tmp_path / "cockpit.json"); monkeypatch.setattr(approval, "get_cockpit_registry", lambda: registry)
    action = CockpitAction("a", "default", "generate_optimization", "Optimize", "simulate", safe_payload={"workspace_id": "default"}); registry.register_action(action)
    pending = approval.create_pending_approval(action)
    decided = approval.decide_approval(pending.approval_id, "approved", "reviewed")
    assert decided.decision == "approved" and registry.get_action("a").status == "approved"
    blocked = CockpitAction("b", "default", "blocked", "Blocked", "no", blocked_reasons=["unsafe"]); registry.register_action(blocked)
    with pytest.raises(ValueError): approval.create_pending_approval(blocked)
