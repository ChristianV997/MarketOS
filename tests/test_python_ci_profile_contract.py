from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PROFILE_PATH = REPO_ROOT / "requirements-test.txt"
DEV_REQUIREMENTS_PATH = REPO_ROOT / "requirements-dev.txt"
PYTHON_VERSION_PATH = REPO_ROOT / ".python-version"


def _jobs():
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]


def _step(job, name):
    return next(step for step in job["steps"] if step.get("name") == name)


def test_canonical_test_profile_includes_runtime_and_development_manifests():
    profile_lines = {
        line.strip()
        for line in PROFILE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert profile_lines == {"-r requirements.txt", "-r requirements-dev.txt"}


def test_test_profile_declares_the_pinned_mergify_pytest_plugin():
    dev_requirements = {
        line.strip()
        for line in DEV_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert "pytest-mergify==2026.9.24.1" in dev_requirements


def test_ci_test_jobs_share_documented_python_version_and_cache_inputs():
    expected_cache_inputs = {
        "requirements-test.txt",
        "requirements.txt",
        "requirements-dev.txt",
    }
    jobs = _jobs()
    python_version = PYTHON_VERSION_PATH.read_text(encoding="utf-8").strip()

    assert python_version == "3.12"

    for job_name in ("test", "quality-advisory"):
        job = jobs[job_name]
        setup_python = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python@"))
        install = _step(job, "Install dependencies")["run"]

        assert setup_python["with"]["python-version"] == python_version
        assert set(setup_python["with"]["cache-dependency-path"].splitlines()) == expected_cache_inputs
        assert install.splitlines() == [
            "python -m pip install --upgrade pip",
            "python -m pip install -r requirements-test.txt",
        ]


def test_mergify_reporting_is_advisory_only_and_required_tests_remain_blocking():
    jobs = _jobs()
    required_test_job = jobs["test"]
    test_step = _step(required_test_job, "Run tests")
    advisory_test_step = _step(jobs["quality-advisory"], "pytest --cov (advisory)")

    required_envs = [required_test_job.get("env", {})] + [
        step.get("env", {}) for step in required_test_job["steps"]
    ]
    assert required_test_job["env"]["MERGIFY_TEST_SELECTION_ENABLE"] == "false"
    assert not any("MERGIFY_TOKEN" in env for env in required_envs)
    assert advisory_test_step["env"]["MERGIFY_TOKEN"] == "${{ secrets.MERGIFY_TOKEN }}"
    assert advisory_test_step["env"]["MERGIFY_TEST_SELECTION_ENABLE"] == "false"
    assert test_step["run"] == "pytest tests/ -v -n auto"
    assert test_step.get("continue-on-error") is not True
    assert required_test_job.get("continue-on-error") is not True
    assert "|| true" not in test_step["run"]
    assert jobs["quality-advisory"].get("continue-on-error") is True
