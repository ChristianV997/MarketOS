from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.ai import operator_context_snapshot as snapshot


def test_schema_constant():
    assert snapshot.SCHEMA == "MarketOS.AIContext.v1"


def test_excluded_paths_drop_artifacts_and_env():
    assert snapshot._excluded_path("artifacts/report.json") is True
    assert snapshot._excluded_path(".env") is True
    assert snapshot._excluded_path("frontend/src/App.tsx") is False
    assert snapshot._safe_changed_paths(["artifacts/x.json", "scripts/ai/foo.py", ".env"]) == ["scripts/ai/foo.py"]


def test_secret_like_and_redact():
    payload = {"token": "secret", "ok": "value", "nested": {"api_key": "x"}}
    assert snapshot._secret_like(payload) is True
    redacted = snapshot._redact(payload)
    assert redacted["token"] == "[redacted]"
    assert redacted["nested"]["api_key"] == "[redacted]"
    assert snapshot._secret_like({"note": "sk-live-abcdefghijklmnopqrstuvwxyz"}) is True


def test_git_argv_not_allowlisted(tmp_path: Path):
    result = snapshot._git(tmp_path, "log", "-1")
    assert result["classification"] == "blocked"


def test_build_snapshot_classifies_unavailable_tools(monkeypatch, tmp_path: Path):
    (tmp_path / "scripts" / "ai").mkdir(parents=True)
    (tmp_path / "scripts" / "phase1_readiness_report.py").write_text("#", encoding="utf-8")
    (tmp_path / "scripts" / "ai" / "session_start.py").write_text("#", encoding="utf-8")
    (tmp_path / "scripts" / "ai" / "select_tests.py").write_text("#", encoding="utf-8")
    (tmp_path / "scripts" / "ai" / "run_local_quality_gate.py").write_text("#", encoding="utf-8")
    (tmp_path / "scripts" / "ai" / "pr_readiness_report.py").write_text("#", encoding="utf-8")

    def fake_git(root, *args, timeout_s=15.0):
        mapping = {
            ("rev-parse", "HEAD"): "abc123",
            ("branch", "--show-current"): "cursor/ai-chat-operator-context-v1",
            ("rev-parse", "origin/main"): "def456",
            ("status", "--porcelain"): "",
            ("remote", "get-url", "origin"): "https://github.com/ChristianV997/MarketOS.git",
        }
        stdout = mapping.get(args, "")
        return {"classification": "actual", "exit_code": 0, "stdout": stdout}

    def fake_run_allowlisted(argv, *, cwd, timeout_s, classification_name):
        parsed = {"status": "not_run", "overall_status": "blocked", "blocking_gates": ["example"], "next_best_action": "inspect"}
        if classification_name == "phase1_readiness":
            parsed = {
                "overall_status": "blocked",
                "overall_score": 38.6,
                "next_best_action": "set_cj_credentials_and_run_validation_pack",
                "blocking_gates": ["cj_credentials_missing_for_live_supplier_proof"],
                "deployment_readiness": {"status": "not_configured"},
            }
        if classification_name == "local_quality_gate":
            parsed = {"status": "not_run", "classification": "ci_unavailable", "mode": "dry_run", "ready_for_supervised_use": False}
        if classification_name == "select_tests":
            parsed = {"recommended_commands": ["git diff --check"]}
        return {"name": classification_name, "classification": "simulated", "exit_code": 0, "parsed": parsed, "reason": None}

    monkeypatch.setattr(snapshot, "_git", fake_git)
    monkeypatch.setattr(snapshot, "_run_allowlisted", fake_run_allowlisted)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)

    document, code = snapshot.build_snapshot(tmp_path, include_github=True, include_frontend=False)
    assert document["schema"] == snapshot.SCHEMA
    assert document["read_only"] is True
    assert document["head_sha"] == "abc123"
    assert document["origin_main_sha"] == "def456"
    assert document["deployment_readiness_classification"] != "actual"
    assert "deployment_not_proven_from_local_checks" in document["current_blockers"]
    assert document["active_pr"] is None
    assert document["evidence_classification"]["github"] == "unavailable"
    assert code == 2


def test_run_allowlisted_blocks_secret_stdout(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"token": "ghp_abcdefghijklmnopqrstuvwxyz1234"}))

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    result = snapshot._run_allowlisted(["python", "x"], cwd=tmp_path, timeout_s=1, classification_name="x")
    assert result["classification"] == "blocked"
    assert result["parsed"] is None
