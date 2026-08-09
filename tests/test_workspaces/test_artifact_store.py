"""Tests for backend.workspaces.artifact_store.ArtifactStore."""
import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))


def test_save_load_json_round_trip():
    store = ArtifactStore()
    ok = store.save("ws-1", "exp-1", "result.json", {"score": 0.9})
    assert ok is True
    assert store.load("ws-1", "exp-1", "result.json") == {"score": 0.9}


def test_load_missing_returns_default():
    store = ArtifactStore()
    assert store.load("ws-1", "exp-missing", "result.json", default={}) == {}


def test_save_load_text_round_trip():
    store = ArtifactStore()
    ok = store.save_text("ws-1", "exp-1", "report.md", "# Hello\n")
    assert ok is True
    assert store.load_text("ws-1", "exp-1", "report.md") == "# Hello\n"


def test_path_for_matches_documented_convention():
    store = ArtifactStore()
    path = store.path_for("ws-1", "exp-1", "result.json")
    assert path.endswith("workspaces/ws-1/experiments/exp-1/result.json") or \
           path.replace("\\", "/").endswith("workspaces/ws-1/experiments/exp-1/result.json")


def test_workspace_isolation_same_filename_no_collision():
    store = ArtifactStore()
    store.save("workspace-a", "exp-1", "result.json", {"owner": "a"})
    store.save("workspace-b", "exp-1", "result.json", {"owner": "b"})

    assert store.load("workspace-a", "exp-1", "result.json")["owner"] == "a"
    assert store.load("workspace-b", "exp-1", "result.json")["owner"] == "b"
    assert store.path_for("workspace-a", "exp-1", "result.json") != store.path_for("workspace-b", "exp-1", "result.json")


def test_list_experiments():
    store = ArtifactStore()
    store.save("ws-1", "exp-a", "result.json", {})
    store.save("ws-1", "exp-b", "result.json", {})
    assert store.list_experiments("ws-1") == ["exp-a", "exp-b"]


def test_list_experiments_empty_workspace_returns_empty_list():
    store = ArtifactStore()
    assert store.list_experiments("never-existed") == []
