"""Tests for orchestrator.main._run_obsidian_sync — Obsidian vault export."""
import time

import pytest

import orchestrator.main as om
from core.content.playbook import Playbook, playbook_memory


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(om._obsidian_sync_limiter, "last_run", 0.0)
    monkeypatch.setattr(om, "_latest_signal_batch", [])
    monkeypatch.setattr(om, "_last_consolidation_result", {})
    monkeypatch.setattr(playbook_memory, "_store", {})
    monkeypatch.setattr(playbook_memory, "_persist", lambda: None)
    yield


def test_skips_when_no_vault_path_configured(monkeypatch):
    monkeypatch.setattr(om, "_OBSIDIAN_VAULT_PATH", "")
    result = om._run_obsidian_sync()
    assert result == {"status": "skipped", "reason": "OBSIDIAN_VAULT_PATH not set"}


def test_rate_limited(monkeypatch, tmp_path):
    monkeypatch.setattr(om, "_OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(om._obsidian_sync_limiter, "last_run", time.time())
    result = om._run_obsidian_sync()
    assert result == {"status": "skipped", "reason": "rate_limited"}


def test_exports_signals_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(om, "_OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(om, "_latest_signal_batch", [{"product": "widget", "score": 0.9}])

    result = om._run_obsidian_sync()

    assert result["status"] == "ok"
    assert result["exported"]["signals"] == 1
    files = list((tmp_path / "signals").glob("*.md"))
    assert len(files) == 1
    assert "widget" in files[0].read_text()


def test_exports_playbooks_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(om, "_OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(playbook_memory, "_store", {
        ("widget", "SCALE"): Playbook(
            product="widget", phase="SCALE", top_hooks=["hook a"],
            top_angles=["angle a"], estimated_roas=2.0, confidence=0.8,
            evidence_count=10,
        ),
    })

    result = om._run_obsidian_sync()

    assert result["exported"]["playbooks"] == 1
    files = list((tmp_path / "playbooks").glob("*.md"))
    assert len(files) == 1


def test_exports_consolidation_insight_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(om, "_OBSIDIAN_VAULT_PATH", str(tmp_path))
    monkeypatch.setattr(om, "_last_consolidation_result", {"cycle_id": "abc123", "episodes_compacted": 5})

    result = om._run_obsidian_sync()

    assert result["exported"]["insights"] == 1
    files = list((tmp_path / "insights").glob("*.md"))
    assert len(files) == 1
    assert "abc123" in files[0].read_text()


def test_nothing_to_export_still_ok(monkeypatch, tmp_path):
    monkeypatch.setattr(om, "_OBSIDIAN_VAULT_PATH", str(tmp_path))
    result = om._run_obsidian_sync()
    assert result == {"status": "ok", "exported": {}}
