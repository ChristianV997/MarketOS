"""Tests for backend.workspaces.artifact_store.ArtifactStore."""
from __future__ import annotations

import json
import os
from pathlib import Path

import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    return tmp_path


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


def test_valid_in_root_path_stays_under_state(tmp_path):
    store = ArtifactStore()
    path = Path(store.path_for("workspace-a", "exp-1", "result.json")).resolve()
    assert str(path).startswith(str(tmp_path.resolve()))
    assert "workspaces/workspace-a/experiments/exp-1/result.json" in path.as_posix()


@pytest.mark.parametrize(
    "workspace_id",
    ["../escape", "../../etc/evil", "a/../../b", ".."],
)
def test_rejects_workspace_id_relative_traversal(workspace_id):
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save(workspace_id, "exp-1", "result.json", {"leaked": True})


def test_rejects_experiment_id_relative_traversal():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "../../escape", "result.json", {"leaked": True})


def test_rejects_filename_relative_traversal():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "exp-1", "../../../escape.json", {"leaked": True})


def test_rejects_absolute_path_filename():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "exp-1", "/etc/passwd", {"leaked": True})


def test_rejects_windows_absolute_path_filename():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("workspace-a", "exp-1", "C:\\Windows\\Temp\\evil.json", {"leaked": True})


def test_rejects_sibling_workspace_escape():
    store = ArtifactStore()
    store.save("workspace-a", "exp-1", "result.json", {"owner": "a"})
    store.save("workspace-b", "exp-1", "result.json", {"owner": "b"})
    with pytest.raises(ValueError):
        store.save("workspace-a", "../workspace-b", "result.json", {"owner": "pwned"})
    assert store.load("workspace-b", "exp-1", "result.json")["owner"] == "b"


def test_cross_client_identity_does_not_collide():
    store = ArtifactStore()
    payload = {"event": "same-id", "seq": 1}
    store.save("client-a", "shared-exp", "artifact.json", payload)
    store.save("client-b", "shared-exp", "artifact.json", {"event": "same-id", "seq": 2})
    assert store.load("client-a", "shared-exp", "artifact.json")["seq"] == 1
    assert store.load("client-b", "shared-exp", "artifact.json")["seq"] == 2


def test_malformed_workspace_identity_is_rejected():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.path_for("", "exp-1", "result.json")
    with pytest.raises(ValueError):
        store.path_for("  ws-1", "exp-1", "result.json")
    with pytest.raises(ValueError):
        store.path_for("ws/nested", "exp-1", "result.json")
    with pytest.raises(ValueError):
        store.path_for("ws-1", "", "result.json")


def test_list_experiments_fails_closed_to_empty_on_traversal():
    store = ArtifactStore()
    assert store.list_experiments("../../../../tmp") == []
    assert store.list_experiments("") == []


def test_load_rejects_traversal_rather_than_reading_outside_state(tmp_path):
    outside = tmp_path.parent / "outside-secret.json"
    outside.write_text('{"secret": true}', encoding="utf-8")
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.load("../..", "exp-1", outside.name)


def test_symlink_escape_is_rejected(tmp_path):
    store = ArtifactStore()
    store.save("workspace-a", "exp-1", "ok.json", {"ok": True})
    workspace_root = tmp_path / "workspaces" / "workspace-a" / "experiments" / "exp-1"
    outside = tmp_path.parent / "symlink-escape-target.json"
    outside.write_text('{"escaped": true}', encoding="utf-8")
    link = workspace_root / "outside.json"
    try:
        os.symlink(outside, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported on this platform")
    with pytest.raises(ValueError):
        store.path_for("workspace-a", "exp-1", "outside.json")
    with pytest.raises(ValueError):
        store.load("workspace-a", "exp-1", "outside.json", default={"safe": True})


def test_malformed_json_artifact_returns_default(tmp_path):
    store = ArtifactStore()
    path = Path(store.path_for("ws-1", "exp-1", "broken.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not-json\n", encoding="utf-8")
    assert store.load("ws-1", "exp-1", "broken.json", default={"recovered": True}) == {"recovered": True}


def test_duplicate_identity_overwrite_stays_in_workspace():
    store = ArtifactStore()
    assert store.save("ws-1", "exp-1", "result.json", {"n": 1}) is True
    assert store.save("ws-1", "exp-1", "result.json", {"n": 2}) is True
    assert store.load("ws-1", "exp-1", "result.json") == {"n": 2}
    assert store.list_experiments("ws-1") == ["exp-1"]


def test_secret_shaped_path_component_is_rejected():
    store = ArtifactStore()
    with pytest.raises(ValueError):
        store.save("ghp_abcdefghijklmnopqrstuvwxyz012345", "exp-1", "result.json", {"ok": True})
    with pytest.raises(ValueError):
        store.save("ws-1", "exp-1", "sk-test-abcdefghijklmnopqrstuvwxyz.json", {"ok": True})


def test_secret_redaction_in_payload():
    store = ArtifactStore()
    ok = store.save(
        "ws-1",
        "exp-1",
        "creds.json",
        {
            "score": 1,
            "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz",
            "note": "safe",
            "nested": {"token": "dummy-token"},
        },
    )
    assert ok is True
    loaded = store.load("ws-1", "exp-1", "creds.json")
    assert loaded["score"] == 1
    assert loaded["note"] == "safe"
    assert loaded["api_key"] == "[redacted]"
    assert loaded["nested"]["token"] == "[redacted]"
    raw = Path(store.path_for("ws-1", "exp-1", "creds.json")).read_text(encoding="utf-8")
    assert "sk-test-abcdefghijklmnopqrstuvwxyz" not in raw


def test_secret_redaction_in_text_payload():
    store = ArtifactStore()
    store.save_text("ws-1", "exp-1", "notes.md", "token=ghp_abcdefghijklmnopqrstuvwxyz0123\n")
    text = store.load_text("ws-1", "exp-1", "notes.md")
    assert "ghp_" not in text
    assert "[redacted]" in text


def test_deterministic_replay_and_lossless_serialization():
    store = ArtifactStore()
    payload = {"score": 0.9, "labels": ["a", "b"], "meta": {"ok": True}}
    store.save("ws-1", "exp-1", "result.json", payload)
    first = store.load("ws-1", "exp-1", "result.json")
    store.save("ws-1", "exp-1", "replay.json", first)
    second = store.load("ws-1", "exp-1", "replay.json")
    assert first == payload
    assert second == payload
    raw = Path(store.path_for("ws-1", "exp-1", "result.json")).read_text(encoding="utf-8")
    assert json.loads(raw) == payload


def test_no_delete_api_and_no_write_outside_tmp(tmp_path):
    store = ArtifactStore()
    assert not hasattr(store, "delete")
    assert not hasattr(store, "remove")
    store.save("ws-1", "exp-1", "result.json", {"ok": True})
    written = list(tmp_path.rglob("result.json"))
    assert len(written) == 1
    assert written[0].resolve().is_relative_to(tmp_path.resolve())
    outside = list(Path("/tmp").glob("evil-artifact-repro/**"))
    assert not any(p.name == "result.json" and "evil-artifact-repro" in str(p) for p in outside)
