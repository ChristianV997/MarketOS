"""Fixture-backed contract: GitLab MR companion stays a bounded, honest gate.

Owns the committed `.gitlab-ci.yml` as the fixture. Enforces:
1. MR-only workflow/job rules (`CI_PIPELINE_SOURCE == "merge_request_event"`).
2. Canonical Python test profile install/cache (`requirements-test.txt` + includes).
3. Blocking companion job (no allow_failure / continue-on-error / `|| true`).
4. Changed-scope selection via `scripts/ai/select_tests.py` with architecture-boundaries fallback.
5. Bounded JUnit/artifacts; no secrets, deploy, or provider-mutation powers.
6. Explicit non-equivalence to GitHub's required full `pytest tests/ -v -n auto` suite.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GITLAB_CI = ROOT / ".gitlab-ci.yml"
PROFILE = ROOT / "requirements-test.txt"
REQUIREMENTS = ROOT / "requirements.txt"
REQUIREMENTS_DEV = ROOT / "requirements-dev.txt"
PYTHON_VERSION = ROOT / ".python-version"
SELECT_TESTS = ROOT / "scripts" / "ai" / "select_tests.py"
GITHUB_CI = ROOT / ".github" / "workflows" / "ci.yml"

MR_RULE = '$CI_PIPELINE_SOURCE == "merge_request_event"'


def _load_gitlab_ci() -> dict:
    assert GITLAB_CI.is_file(), f"missing companion fixture: {GITLAB_CI}"
    data = yaml.safe_load(GITLAB_CI.read_text(encoding="utf-8"))
    assert isinstance(data, dict), ".gitlab-ci.yml must parse as a mapping"
    return data


def _job_script_blobs(job: dict) -> list[str]:
    blobs: list[str] = []
    for key in ("before_script", "script", "after_script"):
        value = job.get(key) or []
        if isinstance(value, str):
            blobs.append(value)
        else:
            blobs.extend(str(item) for item in value)
    return blobs


def test_gitlab_companion_is_merge_request_only_and_blocking():
    data = _load_gitlab_ci()
    workflow_rules = data.get("workflow", {}).get("rules") or []
    assert any(rule.get("if") == MR_RULE for rule in workflow_rules), (
        "workflow.rules must require merge_request_event"
    )

    assert "mr-python-companion" in data, "expected mr-python-companion job"
    job = data["mr-python-companion"]
    job_rules = job.get("rules") or []
    assert any(rule.get("if") == MR_RULE for rule in job_rules), (
        "mr-python-companion.rules must require merge_request_event"
    )
    assert job.get("allow_failure") in (None, False)
    assert job.get("continue-on-error") is not True

    # Failures in install/test/compile must not be masked. Softening git plumbing
    # (`merge-base` / `diff` for changed-scope) is allowed so the honest fallback runs.
    # after_script summary helpers may use `|| true` without affecting job failure.
    blocking_blobs: list[str] = []
    for key in ("before_script", "script"):
        value = job.get(key) or []
        if isinstance(value, str):
            blocking_blobs.append(value)
        else:
            blocking_blobs.extend(str(item) for item in value)
    for blob in blocking_blobs:
        assert "continue-on-error" not in blob
        for line in blob.splitlines():
            stripped = line.strip()
            if "|| true" not in stripped:
                continue
            assert re.search(r"\bgit\s+(merge-base|diff)\b", stripped), (
                f"|| true may only soften git changed-scope plumbing, not tests: {stripped}"
            )
            assert not re.search(r"\b(pytest|pip|compileall)\b", stripped)


def test_gitlab_companion_uses_canonical_requirements_test_profile():
    data = _load_gitlab_ci()
    job = data["mr-python-companion"]
    before = [str(item) for item in (job.get("before_script") or [])]

    assert any("pip install -r requirements-test.txt" in item for item in before), (
        "companion must install the canonical requirements-test.txt profile"
    )
    assert not any(
        re.fullmatch(r"python -m pip install -r requirements\.txt", item.strip())
        for item in before
    ), "obsolete requirements.txt-only install must not remain"

    cache_files = (data.get("cache") or {}).get("key", {}).get("files") or []
    assert cache_files == [
        "requirements-test.txt",
        "requirements.txt",
        "requirements-dev.txt",
    ], f"cache key files drifted: {cache_files}"

    assert PYTHON_VERSION.read_text(encoding="utf-8").strip() == "3.12"
    image = (data.get("default") or {}).get("image") or ""
    assert "python:3.12" in str(image)

    assert PROFILE.is_file() and REQUIREMENTS.is_file() and REQUIREMENTS_DEV.is_file()
    profile_includes = {
        line.strip()
        for line in PROFILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert profile_includes == {"-r requirements.txt", "-r requirements-dev.txt"}


def test_gitlab_companion_changed_scope_selection_and_honest_fallback():
    data = _load_gitlab_ci()
    job = data["mr-python-companion"]
    script = "\n".join(_job_script_blobs(job))

    assert SELECT_TESTS.is_file(), "select_tests helper must exist for changed-scope selection"
    assert "scripts/ai/select_tests.py" in script
    assert "test_architecture_boundaries" in script, (
        "empty/unknown changed set must fall back to architecture-boundaries pytest"
    )

    # Job must not execute GitHub's required full-suite command as a step.
    for blob in _job_script_blobs(job):
        assert "pytest tests/ -v -n auto" not in blob, (
            "companion must not run the GitHub required full suite command"
        )

    text = GITLAB_CI.read_text(encoding="utf-8")
    assert "not a GitHub full-suite equivalent" in text


def test_gitlab_companion_bounds_artifacts_and_forbids_secret_deploy_powers():
    data = _load_gitlab_ci()
    job = data["mr-python-companion"]
    artifacts = job.get("artifacts") or {}
    reports = artifacts.get("reports") or {}

    assert reports.get("junit") == "artifacts/junit.xml"
    paths = artifacts.get("paths") or []
    assert "artifacts/junit.xml" in paths
    assert "artifacts/companion-summary.txt" in paths
    assert artifacts.get("when") == "always"
    assert artifacts.get("expire_in") == "7 days"

    text = GITLAB_CI.read_text(encoding="utf-8")
    assert re.search(r"\$\{\{\s*secrets\.", text) is None
    assert "MERGIFY_TOKEN" not in text
    assert "GITLAB_TOKEN" not in text
    assert "PRIVATE-TOKEN" not in text
    assert re.search(r"(?m)^\s*(deploy|environment|pages)\s*:", text) is None

    # Isolation: companion config must not rewrite GitHub Actions CI.
    assert GITHUB_CI.is_file()
    github_ci = GITHUB_CI.read_text(encoding="utf-8")
    assert "mr-python-companion" not in github_ci
