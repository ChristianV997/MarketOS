from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.ai import operator_context_snapshot as snapshot


def _write_repo(tmp_path: Path) -> Path:
    (tmp_path / "scripts" / "ai").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("# agents\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    for name in (
        "session_start.py",
        "select_tests.py",
        "run_local_quality_gate.py",
        "pr_readiness_report.py",
        "check_dev_stack.py",
        "operator_context_snapshot.py",
    ):
        (tmp_path / "scripts" / "ai" / name).write_text("#\n", encoding="utf-8")
    (tmp_path / "scripts" / "phase1_readiness_report.py").write_text("#\n", encoding="utf-8")
    return tmp_path


def _fake_git_factory(extra: dict[tuple[str, ...], str] | None = None):
    mapping = {
        ("rev-parse", "HEAD"): "abc123",
        ("branch", "--show-current"): "cursor/ai-chat-operator-context-v1",
        ("rev-parse", "origin/main"): "def456",
        ("status", "--porcelain"): "",
        ("remote", "get-url", "origin"): "https://github.com/ChristianV997/MarketOS.git",
        ("rev-parse", "--show-toplevel"): "C:/Users/HP/Documents/MarketOS.worktrees/ai-chat-operator-context-01",
        ("worktree", "list", "--porcelain"): (
            "worktree C:/Users/HP/Documents/MarketOS\nHEAD a7aa895\nbranch refs/heads/antigravity/x\n\n"
            "worktree C:/Users/HP/Documents/MarketOS.worktrees/ai-chat-operator-context-01\n"
            "HEAD abc123\nbranch refs/heads/cursor/ai-chat-operator-context-v1\n"
        ),
        ("merge-base", "origin/main", "HEAD"): "def456",
    }
    if extra:
        mapping.update(extra)

    def fake_git(root, *args, timeout_s=15.0):
        stdout = mapping.get(args, "")
        return {"classification": "actual", "exit_code": 0, "stdout": stdout}

    return fake_git


def _fake_allowlisted(_argv, *, cwd, timeout_s, classification_name):
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
    if classification_name == "development_stack":
        parsed = {"python": "3.12.0", "platform": "win32", "tools": {"git": "git version 2.0", "python": "3.12.0"}}
    if classification_name == "session_start":
        parsed = {"branch": "cursor/ai-chat-operator-context-v1", "changed_paths": []}
    return {"name": classification_name, "classification": "simulated", "exit_code": 0, "parsed": parsed, "reason": None}


def test_schema_constant():
    assert snapshot.SCHEMA == "MarketOS.AIContext.v1"
    assert "repository" in snapshot.REQUIRED_KEYS
    assert "deployment_readiness" in snapshot.REQUIRED_KEYS


def test_excluded_paths_drop_artifacts_and_env():
    assert snapshot._excluded_path("artifacts/report.json") is True
    assert snapshot._excluded_path(".env") is True
    assert snapshot._excluded_path("frontend/src/App.tsx") is False
    assert snapshot._safe_changed_paths(["artifacts/x.json", "scripts/ai/foo.py", ".env"]) == ["scripts/ai/foo.py"]
    assert snapshot._excluded_path("playwright-report/index.html") is True
    assert snapshot._excluded_path("tmp/.cache/data") is True
    assert snapshot._excluded_path("exports/customer/orders.csv") is True


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
    assert snapshot._git(tmp_path, "reset", "--hard")["classification"] == "blocked"
    assert snapshot._git(tmp_path, "checkout", "--", "AGENTS.md")["classification"] == "blocked"
    assert snapshot._git(tmp_path, "worktree", "remove", "x")["classification"] == "blocked"


def test_gh_argv_not_allowlisted(tmp_path: Path):
    result = snapshot._gh(tmp_path, "pr", "merge", "1")
    assert result["classification"] == "blocked"


def test_parse_worktrees_and_drift():
    raw = (
        "worktree C:/Users/HP/Documents/MarketOS\nHEAD aaa\nbranch refs/heads/main\n\n"
        "worktree C:/tmp/other\nHEAD bbb\ndetached\n"
    )
    listed = snapshot._parse_worktrees(raw)
    assert listed[0]["branch"] == "main"
    assert listed[1]["branch"] == "detached"
    safe = [item for item in listed if snapshot._worktree_safe_metadata(item.get("path"))]
    assert len(safe) == 1
    assert snapshot._worktree_safe_metadata("C:/tmp/other") is False
    assert snapshot._worktree_safe_metadata("C:/tmp/.env/MarketOS") is False
    assert snapshot._classify_drift("aaa", "aaa", "aaa") == "aligned"
    assert snapshot._classify_drift("bbb", "aaa", "aaa") == "ahead"
    assert snapshot._classify_drift("aaa", "ccc", "aaa") == "behind"
    assert snapshot._classify_drift("bbb", "ccc", "aaa") == "diverged"
    assert snapshot._classify_drift(None, "aaa", "aaa") == "unavailable"


def test_path_safety_rejects_unexpected_roots(tmp_path: Path):
    missing, reason = snapshot._validate_root(tmp_path / "nope")
    assert missing is None
    assert reason in {"not_a_directory", "unresolvable_path"}
    traversal, traversal_reason = snapshot._validate_root(Path("C:/Users/HP/Documents/MarketOS/../Windows"))
    assert traversal is None
    assert traversal_reason == "path_traversal"
    document, code = snapshot.build_snapshot(tmp_path)
    assert code == 2
    assert "missing_agents_md" in document["blockers"] or "not_a_git_worktree" in document["blockers"]
    assert document["schema"] == snapshot.SCHEMA


def test_build_snapshot_classifies_unavailable_tools(monkeypatch, tmp_path: Path):
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(snapshot, "_git", _fake_git_factory())
    monkeypatch.setattr(snapshot, "_run_allowlisted", _fake_allowlisted)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)

    document, code = snapshot.build_snapshot(repo, include_github=True, include_frontend=False)
    assert document["schema"] == snapshot.SCHEMA
    for key in snapshot.REQUIRED_KEYS:
        assert key in document
    assert document["read_only"] is True
    assert document["HEAD"] == "abc123"
    assert document["origin_main"] == "def456"
    assert document["deployment_readiness"]["classification"] != "actual"
    assert document["deployment_readiness"]["local_checks_are_not_production_proof"] is True
    assert "deployment_not_proven_from_local_checks" in document["blockers"]
    assert document["active_pr"] is None
    assert document["evidence_classifications"]["github"] == "unavailable"
    assert document["evidence_classifications"]["coderos"] in {"not_run", "unavailable"}
    assert document["open_prs"]["classification"] == "unavailable"
    assert document["development_stack"]["classification"] == "simulated"
    assert document["worktree"]["drift"]["vs_origin_main"] == "ahead"
    assert code == 2


def test_build_snapshot_github_not_run_when_disabled(monkeypatch, tmp_path: Path):
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(snapshot, "_git", _fake_git_factory())
    monkeypatch.setattr(snapshot, "_run_allowlisted", _fake_allowlisted)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: "C:/python.exe" if name == "python" else None)
    document, _code = snapshot.build_snapshot(repo, include_github=False)
    assert document["evidence_classifications"]["github"] == "not_run"
    assert document["open_prs"]["classification"] == "not_run"


def test_run_allowlisted_blocks_secret_stdout(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"token": "ghp_abcdefghijklmnopqrstuvwxyz1234"}))

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    result = snapshot._run_allowlisted(["python", "x"], cwd=tmp_path, timeout_s=1, classification_name="x")
    assert result["classification"] == "blocked"
    assert result["parsed"] is None


def test_run_allowlisted_malformed_and_nonzero(monkeypatch, tmp_path: Path):
    def fake_run_not_json(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="not-json")

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run_not_json)
    malformed = snapshot._run_allowlisted(["python", "x"], cwd=tmp_path, timeout_s=1, classification_name="select_tests")
    assert malformed["classification"] == "malformed"
    assert malformed["exit_code"] == 0

    def fake_run_failed(*args, **kwargs):
        return SimpleNamespace(returncode=7, stdout=json.dumps({"ok": True}))

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run_failed)
    failed = snapshot._run_allowlisted(["python", "x"], cwd=tmp_path, timeout_s=1, classification_name="select_tests")
    assert failed["classification"] == "failed"
    assert failed["exit_code"] == 7


def test_run_allowlisted_caps_output(monkeypatch, tmp_path: Path):
    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout="{" + ("a" * (snapshot.MAX_OUTPUT_BYTES + 10)) + "}")

    monkeypatch.setattr(snapshot.subprocess, "run", fake_run)
    result = snapshot._run_allowlisted(["python", "x"], cwd=tmp_path, timeout_s=1, classification_name="x")
    assert result["classification"] == "malformed"
    assert result["reason"] == "output_exceeds_cap"


def test_dirty_worktree_is_not_mutated(monkeypatch, tmp_path: Path):
    repo = _write_repo(tmp_path)
    dirty = repo / "scripts" / "ai" / "notes.txt"
    dirty.write_text("keep me\n", encoding="utf-8")
    extra = {("status", "--porcelain"): "?? scripts/ai/notes.txt"}
    recorded: list[tuple[str, ...]] = []

    def tracking_git(root, *args, timeout_s=15.0):
        recorded.append(args)
        return _fake_git_factory(extra)(root, *args, timeout_s=timeout_s)

    monkeypatch.setattr(snapshot, "_git", tracking_git)
    monkeypatch.setattr(snapshot, "_run_allowlisted", _fake_allowlisted)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)
    document, _code = snapshot.build_snapshot(repo, include_github=False)
    assert dirty.read_text(encoding="utf-8") == "keep me\n"
    assert "scripts/ai/notes.txt" in document["changed_paths"]
    assert document["worktree"]["clean"] is False
    assert all(args[0] not in {"add", "reset", "checkout", "clean", "rm"} for args in recorded)
    assert ("worktree", "remove") not in recorded


def test_coderos_default_is_plan_only_not_run():
    status = snapshot._coderos_status()
    assert status["would_execute"] is False
    assert status["mode"] == "plan_only"
    assert status["classification"] in {"not_run", "unavailable"}


def test_schema_stability_document_keys(monkeypatch, tmp_path: Path):
    repo = _write_repo(tmp_path)
    monkeypatch.setattr(snapshot, "_git", _fake_git_factory())
    monkeypatch.setattr(snapshot, "_run_allowlisted", _fake_allowlisted)
    monkeypatch.setattr(snapshot.shutil, "which", lambda name: None)
    document, _code = snapshot.build_snapshot(repo, include_github=False)
    missing = [key for key in snapshot.REQUIRED_KEYS if key not in document]
    assert missing == []
    encoded = json.dumps(document, ensure_ascii=False)
    assert "ghp_" not in encoded
    assert "artifacts/" not in document["changed_paths"]
    assert document["deployment_readiness_classification"] != "actual"
