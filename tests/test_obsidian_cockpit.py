def test_cockpit_obsidian_sync_skips_without_vault(monkeypatch):
    from backend.obsidian.sync import sync_cockpit_action_note
    from backend.execution_cockpit.cockpit_models import CockpitAction
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    result = sync_cockpit_action_note(CockpitAction("a", "default", "advisory_manual", "Manual", "Review", approval_required=False))
    assert result["status"] in {"skipped", "warning"}
