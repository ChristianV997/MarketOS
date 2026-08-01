"""Tests for backend.workspaces.client_workspace.ClientWorkspace."""
from backend.workspaces.client_workspace import ClientWorkspace


def test_to_dict_from_dict_round_trip():
    ws = ClientWorkspace(
        name="acme-store", workspace_type="client_service", owner_label="Acme Inc",
        mode="client_service", dry_run_default=False, live_mode_enabled=True,
        allowed_integrations=["shopify", "meta_ads"],
        budget_ceiling_monthly=1000.0, budget_ceiling_per_experiment=100.0,
        metadata={"industry": "wellness"},
    )
    restored = ClientWorkspace.from_dict(ws.to_dict())
    assert restored.to_dict() == ws.to_dict()


def test_workspace_id_is_idempotent_for_same_name():
    a = ClientWorkspace(name="own-store")
    b = ClientWorkspace(name="own-store")
    assert a.workspace_id == b.workspace_id


def test_workspace_id_differs_for_different_names():
    a = ClientWorkspace(name="own-store")
    b = ClientWorkspace(name="other-store")
    assert a.workspace_id != b.workspace_id


def test_touch_updates_updated_at():
    ws = ClientWorkspace(name="x")
    before = ws.updated_at
    ws.updated_at = before - 100  # force a detectable change
    ws.touch()
    assert ws.updated_at > before - 100
