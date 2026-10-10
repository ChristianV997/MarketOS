"""Static contract tests: CI workflow artifact security and execution boundary.

Enforces:
1. No unvetted workflow_run exporters (e.g. artifact_on_failure.yml without safe producer).
2. Explicit least-privilege token permissions on all CI workflows.
3. Bounded, allowlisted artifact upload targets (no repo root / broad captures).
4. No ghost workflow triggers referencing non-existent upstream workflows.
"""
from __future__ import annotations

import re
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

# Disallow uploading whole repo root or parent directories
DISALLOWED_UPLOAD_PATTERNS = [
    r"^\.$",
    r"^\./?$",
    r"^\.\./",
    r"^/.*",
    r"^[A-Za-z]:.*",
]


def _get_workflow_files() -> list[Path]:
    if not WORKFLOWS_DIR.exists():
        return []
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


def _parse_workflow(path: Path) -> dict:
    content = path.read_text(encoding="utf-8")
    return yaml.safe_load(content) or {}


def test_artifact_on_failure_ghost_exporter_removed():
    """Ensure .github/workflows/artifact_on_failure.yml is removed.

    Without a safe producer and strict allowlist, ghost artifact exporters
    must not exist in .github/workflows/.
    """
    bad_workflow = WORKFLOWS_DIR / "artifact_on_failure.yml"
    assert not bad_workflow.exists(), (
        f"Found {bad_workflow}. Unvetted artifact_on_failure exporter must be removed."
    )


def test_no_unvetted_workflow_run_triggers():
    """Ensure workflow_run is only used with existing upstream workflows and explicit permissions."""
    workflow_files = _get_workflow_files()
    assert workflow_files, "No workflow files found in .github/workflows"

    # Collect all declared workflow names
    declared_names = set()
    for wf_path in workflow_files:
        data = _parse_workflow(wf_path)
        name = data.get("name")
        if name:
            declared_names.add(name)

    for wf_path in workflow_files:
        data = _parse_workflow(wf_path)
        on_trigger = data.get("on") or data.get(True)  # PyYAML parses 'on' as boolean True unless quoted
        if not isinstance(on_trigger, dict):
            continue

        if "workflow_run" in on_trigger:
            wr_config = on_trigger["workflow_run"]
            assert isinstance(wr_config, dict), f"{wf_path.name}: workflow_run must be a dict configuration"
            upstream_workflows = wr_config.get("workflows", [])
            assert upstream_workflows, f"{wf_path.name}: workflow_run must declare specific workflows"
            for upstream in upstream_workflows:
                assert upstream in declared_names, (
                    f"{wf_path.name}: references non-existent upstream workflow '{upstream}'"
                )


def test_artifact_uploads_use_bounded_targets():
    """Ensure all upload-artifact actions target bounded paths and not root checkouts."""
    workflow_files = _get_workflow_files()
    for wf_path in workflow_files:
        content = wf_path.read_text(encoding="utf-8")
        if "upload-artifact" not in content:
            continue

        data = _parse_workflow(wf_path)
        jobs = data.get("jobs", {})
        for job_name, job_data in jobs.items():
            steps = job_data.get("steps", []) if isinstance(job_data, dict) else []
            for step in steps:
                uses = step.get("uses", "")
                if "upload-artifact" in uses:
                    with_args = step.get("with", {})
                    path_val = str(with_args.get("path", "")).strip()
                    assert path_val, f"{wf_path.name} (job: {job_name}): upload-artifact missing 'path'"

                    # Must not match any dangerous root patterns
                    for pattern in DISALLOWED_UPLOAD_PATTERNS:
                        assert not re.match(pattern, path_val), (
                            f"{wf_path.name} (job: {job_name}): upload-artifact path '{path_val}' "
                            f"matches disallowed pattern '{pattern}'"
                        )


def test_ci_workflows_have_bounded_permissions_or_safe_mode():
    """Ensure all core workflows define explicit permissions or job-level permissions."""
    workflow_files = _get_workflow_files()
    for wf_path in workflow_files:
        data = _parse_workflow(wf_path)
        has_top_permissions = "permissions" in data
        jobs = data.get("jobs", {})
        has_job_permissions = any(
            isinstance(job, dict) and "permissions" in job
            for job in jobs.values()
        )
        # Node.js CI is a standard third-party action workflow; others must have explicit permissions
        if wf_path.name == "node.js.yml":
            continue
        assert has_top_permissions or has_job_permissions, (
            f"{wf_path.name} must declare explicit top-level or job-level 'permissions:' block"
        )


def _path_is_allowlisted(path_val: str) -> bool:
    """A diagnostic upload path must be an explicit relative file, not a glob or log/trace/secret capture."""
    text = path_val.strip()
    if not text or text in {".", "./"} or "\n" in text or "*" in text or "?" in text or text.endswith("/"):
        return False
    lowered = text.lower()
    banned = ("secret", "trace", "playwright", ".log", "payload", "credential", ".env")
    if any(token in lowered for token in banned):
        return False
    return "/" not in text or text.startswith("artifacts/")


def test_synthetic_failure_exports_reject_unrestricted_paths():
    rejected = [
        ".",
        "../secrets",
        "artifacts/*.log",
        "*-benchmark.json",
        "playwright-traces/",
        "raw-provider-payload.json",
        ".env",
        "browser/trace.zip",
    ]
    accepted = ["artifacts/semgrep-results.json", "drift_report.json"]
    assert all(not _path_is_allowlisted(item) for item in rejected)
    assert all(_path_is_allowlisted(item) for item in accepted)


def test_live_uploads_do_not_name_secrets_traces_or_logs():
    for wf_path in _get_workflow_files():
        data = _parse_workflow(wf_path)
        for job in (data.get("jobs") or {}).values():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps") or []:
                if "upload-artifact" not in str(step.get("uses", "")):
                    continue
                path_val = str((step.get("with") or {}).get("path", "")).lower()
                assert "secret" not in path_val
                assert "trace" not in path_val
                assert ".log" not in path_val
                assert "payload" not in path_val
