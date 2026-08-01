from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import scripts.ai.check_dev_stack as check_dev_stack
import scripts.ai.filter_semgrep_output as filter_semgrep_output
import scripts.ai.filter_test_output as filter_test_output
import scripts.ai.generate_session_handoff as generate_session_handoff


def test_filter_test_output_keeps_failure_lines():
    text = """
    collected 3 items
    test_a.py::test_x PASSED
    ============================= FAILURES =============================
    E   AssertionError: boom
    short test summary info
    """
    output = filter_test_output.filter_lines(text)
    assert "FAILURES" in output
    assert "AssertionError" in output
    assert "PASSED" not in output


def test_filter_test_output_keeps_failed_node_and_collection_summary():
    output = filter_test_output.filter_lines(
        "collected 2 items\nfoo.py::test_bad FAILED\nfoo.py::test_ok PASSED\n"
    )
    assert "collected 2 items" in output
    assert "test_bad FAILED" in output
    assert "test_ok PASSED" not in output


def test_filter_semgrep_json_keeps_errors():
    payload = {
        "errors": [{"code": 1}],
        "results": [
            {"check_id": "a", "path": "x.py", "start": {"line": 1}, "extra": {"severity": "INFO"}},
            {"check_id": "b", "path": "y.py", "start": {"line": 2}, "extra": {"severity": "WARNING"}},
        ],
    }
    filtered = filter_semgrep_output.filter_json(payload)
    assert filtered["errors"] == [{"code": 1}]
    assert len(filtered["results"]) == 1
    assert filtered["results"][0]["check_id"] == "b"


def test_generate_session_handoff_uses_git_metadata(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        if "branch" in cmd:
            return SimpleNamespace(stdout="main\n", stderr="")
        if "status" in cmd:
            return SimpleNamespace(stdout=" M file.py\n", stderr="")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(generate_session_handoff.subprocess, "run", fake_run)
    assert generate_session_handoff.git_value(tmp_path, ["branch", "--show-current"]) == "main"
    assert generate_session_handoff.format_status(tmp_path) == " M file.py"
    assert calls[0][0] == "git"


def test_check_dev_stack_detects_repo_and_optional_outputs(monkeypatch, tmp_path):
    repo = tmp_path / "MarketOS"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "ai").mkdir()
    (repo / "scripts").mkdir()
    (repo / "scripts" / "ai").mkdir()
    (repo / "semgrep").mkdir()
    (repo / "semgrep" / "ai-safety.yml").write_text("rules: []", encoding="utf-8")
    monkeypatch.setattr(check_dev_stack.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"python", "git"} else None)
    monkeypatch.setattr(check_dev_stack.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="NAME\n", stderr=""))
    monkeypatch.setattr(check_dev_stack.sys, "version", "3.14.6")
    monkeypatch.setattr(check_dev_stack.os, "environ", {})

    report = check_dev_stack.probe(repo)
    assert report["repository"] == str(repo.resolve())
    assert report["repository_files"]["docs/ai"] is True
    assert report["optional_runtime"]["ollama_models"] is False
    assert report["optional_runtime"]["obsidian_config"] is False
    assert any("Obsidian integration deferred" in item for item in check_dev_stack.recommendations(report))
