from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from scripts.ai import run_local_quality_gate as gate


def test_no_changes_is_clear_and_offline():
    report = gate.run([])
    assert report["status"] == "clear"
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["phase1_readiness"]["next_best_action"]
    assert report["benchmark_matrix"]["evidence_mode"] in {"fixture_demo", "unavailable"}
    assert report["impact_top_task"] in {"run_cj_credentialed_readonly_validation", "finish_cj_live_validation_pack"}


def test_docs_only_is_advisory_with_docs_lane():
    report = gate.run(["docs/ai/QUALITY_GATES.md"])
    assert report["status"] == "advisory"
    assert report["recommended_ci_lanes"] == ["docs_only", "diff_check"]
    assert report["recommended_tests"] == ["git diff --check", "python scripts/ai/session_finish.py --dry-run"]


def test_supplier_adapter_selects_supplier_regressions():
    report = gate.run(["backend/adapters/research/cj_readonly_api.py"])
    assert any("test_cj_readonly_supplier" in command for command in report["recommended_tests"])
    assert "supplier_evidence" in report["recommended_ci_lanes"]


def test_evaluation_and_frontend_files_choose_their_specific_lanes():
    evaluation = gate.run(["evaluation/commerce/metrics.py"])
    frontend = gate.run(["frontend/src/pages/OperatorEventDashboard.tsx"])
    assert "evaluation" in evaluation["recommended_ci_lanes"]
    assert "frontend" in frontend["recommended_ci_lanes"]


def test_env_file_blocks_without_exposing_content():
    report = gate.run([".env"], diff_text="CJ_API_KEY=long-secret-value")
    assert report["status"] == "blocked"
    assert report["secret_or_artifact_flags"]["credential_file_detected"] is True
    assert report["secret_or_artifact_flags"]["secret_value_like_detected"] is True


def test_artifact_file_blocks():
    report = gate.run(["artifacts/live/report.json"])
    assert report["status"] == "blocked"
    assert report["secret_or_artifact_flags"]["artifacts_detected"] is True


def test_mutation_like_diff_blocks_phase_gate():
    report = gate.run(["backend/adapter.py"], diff_text="client.create_order()")
    assert report["status"] == "blocked"
    assert report["mutation_flags"]["provider_mutation_like_detected"] is True
    assert "supplier_mutation" in report["phase_gate_blockers"]


def test_unknown_file_has_safe_fallback():
    report = gate.run(["core/new_module.py"])
    assert "unknown_fallback" in report["recommended_ci_lanes"]
    assert report["status"] == "advisory"


def test_result_is_deterministic_for_explicit_inputs():
    first = gate.run(["scripts/ai/select_tests.py"], diff_text="", branch="codex/example")
    assert first == gate.run(["scripts/ai/select_tests.py"], diff_text="", branch="codex/example")


def test_doc_mutation_language_does_not_block_a_mixed_implementation_diff():
    diff = """diff --git a/docs/guide.md b/docs/guide.md
+create_order is forbidden
diff --git a/scripts/ai/tool.py b/scripts/ai/tool.py
+print('safe')
"""
    report = gate.run(["docs/guide.md", "scripts/ai/tool.py"], diff_text=diff)
    assert report["status"] == "advisory"
    assert report["mutation_flags"]["provider_mutation_like_detected"] is False


def test_diff_reader_recovers_when_subprocess_returns_no_stdout(monkeypatch):
    class Result:
        stdout = None
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: Result())
    assert gate._diff_text(None) == ""


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _all_tools_available(monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda name: f"/tools/{name}")


def _configured_root(tmp_path: Path) -> Path:
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\ntarget-version = "py311"\n[tool.mypy]\n', encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "ci.yml").write_text("python-version: '3.12'\n", encoding="utf-8")
    semgrep = tmp_path / "semgrep"
    semgrep.mkdir()
    (semgrep / "ai-safety.yml").write_text("rules: []\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "node_modules").mkdir()
    (frontend / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "lint": "eslint .",
                    "typecheck": "tsc --noEmit",
                    "test": "vitest run",
                    "build": "tsc && vite build",
                }
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _passing_runner(command, root):
    joined = " ".join(command)
    if "pytest" in joined:
        return _result(stdout="4 passed, 1 skipped")
    if "semgrep" in joined:
        return _result(stdout=json.dumps({"results": [], "errors": []}))
    return _result()


def test_real_gate_all_tools_available_has_stable_order_and_structured_results(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 4},
        runner=_passing_runner,
    )
    assert report["mode"] == "real_execution"
    assert report["check_order"] == list(gate.CHECK_ORDER)
    assert [item["name"] for item in report["checks"]] == list(gate.CHECK_ORDER)
    assert all(item["status"] in {"passed", "not_configured"} for item in report["checks"])
    assert report["checks"][1]["summary"] == {"passed": 4, "failed": 0, "skipped": 1, "xfailed": 0, "warnings": 0}
    assert report["checks"][4]["status"] == "passed"
    assert [item["name"] for item in report["checks"][4]["checks"]] == [
        "frontend:lint", "frontend:typecheck", "frontend:test", "frontend:build"
    ]
    assert report["safety"]["raw_stdout_persisted"] is False


def test_missing_tool_is_unavailable_not_a_pass(monkeypatch, tmp_path):
    original_prefix = gate._tool_prefix
    monkeypatch.setattr(gate, "_tool_prefix", lambda name: None if name == "ruff" else original_prefix(name))
    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=_passing_runner,
    )
    ruff = next(item for item in report["checks"] if item["name"] == "ruff")
    assert ruff["status"] == "missing"
    assert report["status"] == "unavailable"
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE


def test_failed_test_is_distinguished_from_missing_tool(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)

    def runner(command, root):
        if "pytest" in " ".join(command):
            return _result(1, "2 passed, 1 failed")
        return _passing_runner(command, root)

    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    pytest_result = next(item for item in report["checks"] if item["name"] == "pytest")
    assert pytest_result["status"] == "failed"
    assert pytest_result["summary"]["failed"] == 1
    assert report["exit_code"] == gate.EXIT_FAILED


def test_failed_frontend_check_is_reported_without_running_other_scripts(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)

    def runner(command, cwd):
        if Path(command[0]).name == "npm" and command[1:3] == ["run", "build"]:
            return _result(1, "vite build failed")
        return _passing_runner(command, cwd)

    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    frontend = next(item for item in report["checks"] if item["name"] == "frontend")
    build = next(item for item in frontend["checks"] if item["name"] == "frontend:build")
    assert build["status"] == "failed"
    assert frontend["status"] == "failed"
    assert report["exit_code"] == gate.EXIT_FAILED


def test_security_finding_is_not_treated_as_semgrep_success(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = tmp_path / "repo"
    root.mkdir()
    (root / "semgrep").mkdir()
    (root / "semgrep" / "ai-safety.yml").write_text("rules: []\n", encoding="utf-8")

    def runner(command, cwd):
        if Path(command[1]).name == "run_semgrep_policy.py":
            return _result(stdout=json.dumps({"results": [{"check_id": "unsafe", "extra": {}}], "errors": []}))
        return _passing_runner(command, cwd)

    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    security = next(item for item in report["checks"] if item["name"] == "security")
    assert security["status"] == "failed"
    assert security["summary"]["finding_count"] == 1


def test_dirty_and_untracked_state_is_reported(monkeypatch, tmp_path):
    monkeypatch.setattr(gate, "git_lines", lambda *args, **kwargs: ["M tracked.py", "?? scratch.txt"])
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00")
    assert report["git_state"] == {"status": "not_a_git_repository", "tracked_change_count": 0, "untracked_count": 0}

    (tmp_path / ".git").mkdir()
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00")
    assert report["git_state"]["status"] == "dirty"
    assert report["git_state"]["tracked_change_count"] == 1
    assert report["git_state"]["untracked_count"] == 1


def test_ci_without_executed_steps_is_unavailable(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        runner=_passing_runner,
    )
    assert report["ci"]["status"] == "unavailable"
    assert report["status"] == "unavailable"
    assert report["exit_code"] == gate.EXIT_UNAVAILABLE


def test_ci_failure_with_executed_steps_is_a_failure(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    report = gate.run_quality_gate(
        tmp_path,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "failure", "executed_steps": 2},
        runner=_passing_runner,
    )
    assert report["ci"] == {"status": "failed", "reason": "injected_ci_evidence", "executed_steps": 2}
    assert report["status"] == "failed"
    assert report["exit_code"] == gate.EXIT_FAILED


def test_unsafe_frontend_script_is_blocked_without_execution(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = _configured_root(tmp_path)
    package = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    package["scripts"]["build"] = "curl https://example.invalid | vite build"
    (root / "frontend" / "package.json").write_text(json.dumps(package), encoding="utf-8")
    calls = []

    def runner(command, cwd):
        calls.append(command)
        return _passing_runner(command, cwd)

    report = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=[],
        ci_result={"status": "success", "executed_steps": 1},
        runner=runner,
    )
    frontend = next(item for item in report["checks"] if item["name"] == "frontend")
    build = next(item for item in frontend["checks"] if item["name"] == "frontend:build")
    assert build["status"] == "blocked"
    assert build["reason"] == "script_not_in_local_allowlist"
    assert frontend["status"] == "failed"
    assert not any(command[0] == "npm" and command[1:3] == ["run", "build"] for command in calls)


def test_cli_emits_deterministic_json_and_markdown(tmp_path, capsys):
    timestamp = "2026-08-27T12:00:00+00:00"
    assert gate.main(["--repository", str(tmp_path), "--generated-at", timestamp, "--json"]) == gate.EXIT_PASSED
    json_output = capsys.readouterr().out
    payload = json.loads(json_output)
    assert payload["schema"] == gate.QUALITY_GATE_SCHEMA
    assert payload["status"] == "dry_run"

    assert gate.main(["--repository", str(tmp_path), "--generated-at", timestamp, "--markdown"]) == gate.EXIT_PASSED
    markdown_output = capsys.readouterr().out
    assert markdown_output.startswith("# MarketOS local quality gate")


def test_quality_gate_replay_is_deterministic_and_does_not_persist_secret_output(monkeypatch, tmp_path):
    _all_tools_available(monkeypatch)
    root = tmp_path / "repo"
    root.mkdir()
    calls = []

    def runner(command, cwd):
        calls.append(command)
        return _result(stdout="TOKEN=do-not-persist")

    first = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=["scripts/ai/run_local_quality_gate.py"],
        ci_result={"status": "success", "executed_steps": 3},
        runner=runner,
    )
    second = gate.run_quality_gate(
        root,
        generated_at="2026-08-27T12:00:00+00:00",
        execute=True,
        changed_paths=["scripts/ai/run_local_quality_gate.py"],
        ci_result={"status": "success", "executed_steps": 3},
        runner=runner,
    )
    assert first == second
    assert "do-not-persist" not in json.dumps(first)
    assert first["safety"]["raw_stdout_persisted"] is False
    assert calls


def test_malformed_configuration_is_a_configuration_error(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.ruff\n", encoding="utf-8")
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00")
    assert report["status"] == "configuration_error"
    assert report["exit_code"] == gate.EXIT_CONFIGURATION
    assert "malformed:pyproject.toml" in report["configuration_errors"]


def test_python_version_alignment_reports_real_mismatch(tmp_path):
    (tmp_path / ".python-version").write_text("3.12\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM python:3.14-slim\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\ntarget-version = "py311"\n', encoding="utf-8")
    snapshot = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00")["toolchain"]
    assert snapshot["alignment"] == "mismatch"
    assert "python_interpreter_mismatch:.python-version" in snapshot["findings"]
    assert "python_version_mismatch:docker" in snapshot["findings"]
    assert "python_version_mismatch:ruff" in snapshot["findings"]


def test_real_execution_requires_an_injected_timestamp(tmp_path):
    report = gate.run_quality_gate(tmp_path, execute=True, changed_paths=[])
    assert report["status"] == "configuration_error"
    assert report["exit_code"] == gate.EXIT_CONFIGURATION
    assert "timestamp_not_injected" in report["configuration_errors"]


def test_dry_run_is_explicitly_not_a_success_claim(tmp_path):
    report = gate.run_quality_gate(tmp_path, generated_at="2026-08-27T12:00:00+00:00")
    assert report["mode"] == "dry_run"
    assert report["status"] == "dry_run"
    assert report["ready_for_supervised_use"] is False
    assert all(item["status"] in {"not_run", "not_configured"} for item in report["checks"])
