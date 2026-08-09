from backend.execution_cockpit.cockpit_models import CockpitAction
from backend.execution_cockpit.cockpit_registry import CockpitRegistry


def test_cockpit_registry_persists_and_filters(tmp_path):
    registry = CockpitRegistry(tmp_path / "cockpit.json")
    item = CockpitAction("a", "ws", "advisory_manual", "Manual", "review", approval_required=False)
    registry.register_action(item)
    loaded = CockpitRegistry(tmp_path / "cockpit.json")
    assert loaded.get_action("a").workspace_id == "ws"
    assert loaded.list_actions(workspace_id="ws")[0].action_id == "a"
