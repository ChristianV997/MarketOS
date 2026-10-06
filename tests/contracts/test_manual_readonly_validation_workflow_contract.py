"""Contract tests for manual CJ read-only validation workflow and environment isolation."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "manual-readonly-validation.yml"
GITIGNORE_PATH = ROOT / ".gitignore"


def _load_workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.exists(), f"Workflow file not found: {WORKFLOW_PATH}"
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    return yaml.safe_load(content)


def test_manual_validation_workflow_least_privilege_permissions():
    """Verify workflow and job level permissions adhere to least privilege (contents: read)."""
    data = _load_workflow()
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    # Workflow-level permissions
    assert "permissions" in data, "Workflow must declare top-level permissions"
    assert data["permissions"] == {"contents": "read"}

    # Job-level permissions
    jobs = data.get("jobs", {})
    assert "readonly-validation" in jobs, "readonly-validation job must exist"
    job = jobs["readonly-validation"]
    assert job.get("permissions") == {"contents": "read"}, "Job must explicitly restrict permissions to contents: read"

    # Ensure no write permissions anywhere
    assert "write" not in raw_text.lower() or "read-only" in raw_text.lower()
    for perm_scope in ("contents", "actions", "checks", "deployments", "issues", "packages", "pull-requests", "statuses"):
        if isinstance(data["permissions"], dict):
            assert data["permissions"].get(perm_scope) != "write"
        if isinstance(job.get("permissions"), dict):
            assert job["permissions"].get(perm_scope) != "write"


def test_manual_validation_workflow_does_not_inject_secrets_or_enable_live_calls():
    """Supplier steps stay offline: no credentials, no live flag, no network opt-in."""
    data = _load_workflow()
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    job = data["jobs"]["readonly-validation"]

    assert job.get("env", {}) == {}
    assert "secrets." not in raw_text
    assert "CJ_EMAIL" not in raw_text
    assert "CJ_API_KEY" not in raw_text
    assert "MARKETOS_SUPPLIER_AUTH_READONLY" not in raw_text
    assert "--allow-network" not in raw_text
    assert "upload-artifact" not in raw_text
    assert "actions/upload-artifact" not in raw_text

    for step in job.get("steps", []):
        step_env = step.get("env", {})
        assert "CJ_EMAIL" not in step_env
        assert "CJ_API_KEY" not in step_env
        assert not any("secrets." in str(value) for value in step_env.values())
        assert "--allow-network" not in step.get("run", "")


def test_manual_validation_workflow_rejects_unbounded_inputs_without_echoing_them():
    """The advertised candidate cap is the pack's hard cap, and bad input fails closed."""
    data = _load_workflow()
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    triggers = data.get(True) or data.get("on") or {}
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in raw_text
    assert "schedule:" not in raw_text
    assert "\n  push:" not in raw_text and "\non:\n  push:" not in raw_text

    guard = next(step for step in data["jobs"]["readonly-validation"]["steps"] if "invalid_dispatch_input" in step.get("run", ""))
    assert guard["env"]["MAX_CANDIDATES"] == "${{ inputs.max_candidates }}"
    assert guard["env"]["CANDIDATE_QUERY"] == "${{ inputs.candidate_query }}"
    assert 'limit != "1"' in guard["run"]
    assert "invalid_dispatch_input" in guard["run"]
    assert "os.environ" in guard["run"]
    assert "${{ inputs.candidate_query }}" not in guard["run"]
    assert job_timeout(data) == 15
    checkout = next(step for step in data["jobs"]["readonly-validation"]["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def job_timeout(data: dict[str, Any]) -> int:
    return data["jobs"]["readonly-validation"]["timeout-minutes"]


def _minimal_subprocess_environment(**overrides: str) -> dict[str, str]:
    """Pass only platform runtime variables and synthetic inputs to child processes."""
    allowed = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT", "HOME", "MSYSTEM")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(overrides)
    return environment


def _run_dispatch_guard(query: str, max_candidates: str) -> subprocess.CompletedProcess[str]:
    """Execute the workflow's embedded guard with env-only dispatch inputs."""
    data = _load_workflow()
    guard = next(
        step for step in data["jobs"]["readonly-validation"]["steps"] if "invalid_dispatch_input" in step.get("run", "")
    )
    command = guard["run"].strip()
    prefix = "python -c '"
    assert command.startswith(prefix) and command.endswith("'"), "Guard must remain a single quoted Python command"

    environment = _minimal_subprocess_environment(CANDIDATE_QUERY=query, MAX_CANDIDATES=max_candidates)
    return subprocess.run(
        [sys.executable, "-c", command[len(prefix) : -1]],
        cwd=str(ROOT),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


@pytest.mark.parametrize(
    ("query", "max_candidates"),
    [
        ("dispatch-secret-malformed", "2"),
        ("dispatch-secret-zero", "0"),
        ("dispatch-secret-empty-limit", ""),
        ("dispatch-secret-whitespace-limit", " 1 "),
        ("", "1"),
        (" " * 3, "1"),
        (" \t\n ", "1"),
        ("dispatch-secret-" + ("x" * 121), "1"),
        ("dispatch-secret-control\x1f", "1"),
        ("dispatch-secret-del\x7f", "1"),
    ],
    ids=[
        "malformed-limit",
        "zero-limit",
        "empty-limit",
        "whitespace-limit",
        "empty-query",
        "spaces-only-query",
        "tab-newline-control-query",
        "oversized-query",
        "control-character-query",
        "delete-character-query",
    ],
)
def test_manual_validation_dispatch_guard_rejects_bad_inputs_without_echoing(query: str, max_candidates: str):
    """Malformed, empty, oversized, and control-character inputs fail closed without disclosure."""
    result = _run_dispatch_guard(query, max_candidates)
    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "invalid_dispatch_input\n"
    if query:
        assert query not in output
    if max_candidates:
        assert max_candidates not in output


@pytest.mark.parametrize(
    "query",
    ["portable espresso maker", "x" * 120],
    ids=["default-query", "maximum-query-length"],
)
def test_manual_validation_dispatch_guard_accepts_bounded_input(query: str):
    """The default and maximum-length bounded dispatch values pass the guard."""
    result = _run_dispatch_guard(query, "1")

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""



def test_manual_validation_workflow_safe_input_handling_no_shell_interpolation():
    """Verify dispatch inputs are passed through environment variables and never interpolated into shell text."""
    data = _load_workflow()
    job = data["jobs"]["readonly-validation"]

    # Check that no `run:` line directly interpolates ${{ inputs.* }}
    for step in job.get("steps", []):
        run_script = step.get("run", "")
        if run_script:
            # Check for ${{ inputs.* }} direct interpolation inside run strings
            interpolated_inputs = re.findall(r"\$\{\{\s*inputs\.[a-zA-Z0-9_-]+\s*\}\}", run_script)
            assert not interpolated_inputs, (
                f"Direct input interpolation found in run script: {run_script}. "
                "Inputs must be mapped to step env vars and referenced as $VAR."
            )

    # Check validation step maps candidate_query via env and references $CANDIDATE_QUERY
    validation_step = next(
        step for step in job["steps"]
        if "run_phase1_cj_readonly_validation_pack.py" in step.get("run", "")
    )
    assert "CANDIDATE_QUERY" in validation_step.get("env", {}), "candidate_query input must be passed via env"
    assert validation_step["env"]["CANDIDATE_QUERY"] == "${{ inputs.candidate_query }}"
    assert '--query "$CANDIDATE_QUERY"' in validation_step["run"], (
        "Run command must pass $CANDIDATE_QUERY as one quoted argument"
    )


def test_manual_validation_shell_looking_query_remains_one_inert_argument(tmp_path: Path):
    """Run the workflow's exact shell command with a local Python stub, never the CJ pack."""
    data = _load_workflow()
    validation_step = next(
        step for step in data["jobs"]["readonly-validation"]["steps"]
        if "run_phase1_cj_readonly_validation_pack.py" in step.get("run", "")
    )
    bash = shutil.which("bash")
    assert bash is not None, "Bash is required to exercise the Ubuntu workflow shell contract"

    query = "espresso maker $(touch shell-injection-marker); printf INJECTED"
    capture = 'python() { printf "%s\\0" "$@"; }\n' + validation_step["run"]
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", capture],
        cwd=tmp_path,
        env=_minimal_subprocess_environment(CANDIDATE_QUERY=query),
        capture_output=True,
        check=False,
        timeout=5,
    )

    expected_args = [
        b"scripts/run_phase1_cj_readonly_validation_pack.py",
        b"--provider",
        b"cj",
        b"--query",
        query.encode("utf-8"),
        b"--markdown",
    ]
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    separator = bytes((0,))
    assert result.stdout == separator.join(expected_args) + separator
    assert not (tmp_path / "shell-injection-marker").exists()


def test_gitignore_ignores_env_variants_while_retaining_examples():
    """Verify .gitignore ignores .env and .env.* while retaining .env.example files."""
    gitignore_content = GITIGNORE_PATH.read_text(encoding="utf-8")
    lines = [line.strip() for line in gitignore_content.splitlines()]

    # Ensure ignore patterns are present
    assert ".env" in lines
    assert ".env.*" in lines
    assert "!.env.example" in lines

    # Test path resolution against git check-ignore using subprocess
    test_paths = [
        (".env", True),
        (".env.local", True),
        (".env.production", True),
        (".env.test", True),
        (".env.development.local", True),
        ("deploy/mvp/.env.mvp", True),
        (".env.example", False),
        ("frontend/.env.example", False),
        ("deploy/mvp/.env.mvp.example", False),
    ]

    for path_str, should_be_ignored in test_paths:
        result = subprocess.run(
            ["git", "check-ignore", "-q", path_str],
            cwd=str(ROOT),
            timeout=5,
        )
        is_ignored = (result.returncode == 0)
        assert is_ignored == should_be_ignored, (
            f"Path '{path_str}' expected ignored={should_be_ignored}, got ignored={is_ignored}"
        )


def test_manual_validation_workflow_has_no_hardcoded_secrets():
    """Verify workflow contains no raw secrets or tokens."""
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    for line in content.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("#"):
            continue
        assert "password:" not in trimmed.lower()
        assert "token:" not in trimmed.lower() or "secrets." in trimmed or "github.token" in trimmed
        assert not re.search(r"\b(?:sk|rk|pk)_[A-Za-z0-9_-]{8,}\b", trimmed)
        assert "bearer " not in trimmed.lower()
