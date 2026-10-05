"""Contract tests for manual CJ read-only validation workflow and environment isolation."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

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
    assert '$CANDIDATE_QUERY' in validation_step["run"] or '"$CANDIDATE_QUERY"' in validation_step["run"], (
        "Run command must safely reference $CANDIDATE_QUERY"
    )


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
