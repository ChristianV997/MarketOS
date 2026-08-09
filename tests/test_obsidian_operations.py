def test_operations_sync_skips_without_vault(monkeypatch):
    from backend.obsidian.client import ObsidianClient
    from backend.obsidian.sync import sync_operating_plan_note
    from backend.operations.task_models import OperatingPlan
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = sync_operating_plan_note(OperatingPlan("p", "default", "Plan", "objective"))
    assert result["status"] in {"skipped", "warning"}
