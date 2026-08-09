"""Tests for backend.workspaces.registry.WorkspaceRegistry."""
import os

from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry


def test_register_get_by_name_list_all(tmp_path):
    reg = WorkspaceRegistry(path=str(tmp_path / "workspaces.json"))
    ws = ClientWorkspace(name="own-store")
    reg.register(ws)

    assert reg.get(ws.workspace_id).name == "own-store"
    assert reg.by_name("own-store").workspace_id == ws.workspace_id
    assert len(reg.list_all()) == 1


def test_get_unknown_returns_none(tmp_path):
    reg = WorkspaceRegistry(path=str(tmp_path / "workspaces.json"))
    assert reg.get("nonexistent") is None
    assert reg.by_name("nonexistent") is None


def test_persists_across_fresh_instance(tmp_path):
    path = str(tmp_path / "workspaces.json")
    reg1 = WorkspaceRegistry(path=path)
    ws = ClientWorkspace(name="own-store")
    reg1.register(ws)

    reg2 = WorkspaceRegistry(path=path)  # simulates a fresh process/restart
    assert reg2.get(ws.workspace_id) is not None
    assert reg2.get(ws.workspace_id).name == "own-store"


def test_update_bumps_updated_at_and_persists(tmp_path):
    reg = WorkspaceRegistry(path=str(tmp_path / "workspaces.json"))
    ws = ClientWorkspace(name="own-store")
    reg.register(ws)
    original_updated = ws.updated_at

    ws.live_mode_enabled = True
    reg.update(ws)

    reloaded = reg.get(ws.workspace_id)
    assert reloaded.live_mode_enabled is True
    assert reloaded.updated_at >= original_updated


def test_register_creates_parent_directory(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "workspaces.json")
    reg = WorkspaceRegistry(path=path)
    reg.register(ClientWorkspace(name="x"))
    assert os.path.exists(path)
