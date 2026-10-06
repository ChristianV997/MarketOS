"""Adversarial contract tests for fail-closed promotion CI evidence."""
from types import SimpleNamespace
from typing import Any

import pytest

from backend.deployment import promotion_rehearsal as rehearsal
from backend.deployment.promotion_rehearsal import (
    classify_ci_evidence,
    classify_github_actions_job,
    execute_promotion_rehearsal,
)


@pytest.mark.parametrize(
    "malformed_fields",
    [
        pytest.param({"logs_available": 1}, id="integer-logs-flag"),
        pytest.param({"logs_available": "true"}, id="string-logs-flag"),
        pytest.param({"total_steps": True}, id="boolean-step-count"),
        pytest.param({"total_steps": 3.0}, id="float-step-count"),
        pytest.param({"total_steps": -1}, id="negative-step-count"),
        pytest.param({"total_steps": "3"}, id="string-step-count"),
        pytest.param({"runners_active": True}, id="boolean-runner-count"),
        pytest.param({"runners_active": 1.0}, id="float-runner-count"),
        pytest.param({"runners_active": -1}, id="negative-runner-count"),
        pytest.param({"runners_active": "1"}, id="string-runner-count"),
    ],
)
def test_abstract_ci_evidence_rejects_malformed_fields(malformed_fields: dict[str, object]) -> None:
    evidence = {
        "ci_status": "passed",
        "total_steps": 3,
        "runners_active": 1,
        "logs_available": True,
    }
    evidence.update(malformed_fields)

    result = classify_ci_evidence(**evidence)

    assert result["state"] == "ci_unavailable"


def test_well_typed_ci_evidence_can_pass() -> None:
    result = classify_ci_evidence(
        ci_status="passed",
        total_steps=3,
        runners_active=1,
        logs_available=True,
    )

    assert result["state"] == "passed"


def _successful_job() -> dict[str, object]:
    return {
        "status": "completed",
        "runner_id": 42,
        "steps": [{"name": "pytest", "conclusion": "success"}],
        "conclusion": "success",
    }


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("missing_status", id="missing-status"),
        pytest.param("unknown_status", id="unknown-status"),
        pytest.param("fractional_runner_id", id="fractional-runner-id"),
        pytest.param("malformed_step_entries", id="non-mapping-step-entries"),
        pytest.param("step_missing_name", id="step-missing-name"),
        pytest.param("step_missing_conclusion", id="step-missing-conclusion"),
        pytest.param("integer_non_boolean_logs", id="integer-non-boolean-logs"),
        pytest.param("truthy_non_boolean_logs", id="truthy-non-boolean-logs"),
    ],
)
def test_github_actions_job_rejects_malformed_evidence(case: str) -> None:
    job = _successful_job()
    logs_available: Any = True

    if case == "missing_status":
        job.pop("status")
    elif case == "unknown_status":
        job["status"] = "unknown"
    elif case == "fractional_runner_id":
        job["runner_id"] = 3.7
    elif case == "malformed_step_entries":
        job["steps"] = ["not-a-step", None, 42]
    elif case == "step_missing_name":
        job["steps"] = [{"conclusion": "success"}]
    elif case == "step_missing_conclusion":
        job["steps"] = [{"name": "pytest"}]
    elif case == "integer_non_boolean_logs":
        logs_available = 1
    elif case == "truthy_non_boolean_logs":
        logs_available = "false"

    result = classify_github_actions_job(job, logs_available=logs_available)

    assert result["state"] == "ci_unavailable"


def test_github_actions_job_with_complete_typed_success_evidence_can_pass() -> None:
    result = classify_github_actions_job(_successful_job(), logs_available=True)

    assert result["state"] == "passed"
    assert result["steps_executed"] == 1


def test_github_actions_job_does_not_count_skipped_steps_as_execution() -> None:
    job = _successful_job()
    job["steps"] = [{"name": "conditional", "conclusion": "skipped"}]

    result = classify_github_actions_job(job, logs_available=True)

    assert result["state"] == "ci_unavailable"
    assert result["steps_executed"] == 0


@pytest.mark.parametrize(
    "runner_id",
    [
        pytest.param(True, id="boolean-runner-id"),
        pytest.param(3.0, id="integral-float-runner-id"),
        pytest.param(-1, id="negative-runner-id"),
        pytest.param("3", id="numeric-string-runner-id"),
    ],
)
def test_github_actions_job_rejects_non_integer_runner_ids(runner_id: Any) -> None:
    job = {**_successful_job(), "runner_id": runner_id}

    result = classify_github_actions_job(job, logs_available=True)

    assert result["state"] == "ci_unavailable"


def test_malformed_github_actions_evidence_blocks_final_readiness_when_other_gates_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    revision = "a" * 40
    repository = {
        "commit_sha": revision,
        "branch": "synthetic",
        "worktree_path": str(tmp_path),
        "is_isolated_worktree": False,
        "clean": True,
        "dirty_file_count": 0,
    }
    monkeypatch.setattr(rehearsal, "get_repository_identity", lambda: repository)
    monkeypatch.setattr(rehearsal, "get_runtime_versions", lambda: {"python": "3.12"})
    monkeypatch.setattr(rehearsal, "check_container_static_hardening", lambda _path: {"status": "passed"})
    monkeypatch.setattr(
        rehearsal,
        "run_all_diagnostics",
        lambda *, environ, mode, ci_evidence: {
            "summary": {"status": "all_checks_healthy", "detected_issues": 0, "total_checks": 1},
            "diagnostics": [
                {
                    "code": "zero_step_ci",
                    "category": "continuous_integration",
                    "status": "ok" if ci_evidence["ci_status"] == "passed" else "detected",
                    "message": "Synthetic CI evidence status.",
                    "remediation": "Collect valid CI proof.",
                    "failure_details": {
                        "ci_status": ci_evidence["ci_status"],
                        "steps_executed": ci_evidence["steps_executed"],
                        "runner_id": ci_evidence["runner_id"],
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        rehearsal,
        "validate_environment",
        lambda *, environ, mode: SimpleNamespace(ready=True, blockers=[], warnings=[]),
    )
    monkeypatch.setattr(
        rehearsal,
        "inspect_coderos_status",
        lambda *, environ: {"status": "unavailable", "runtime_imports_allowed": False},
    )
    monkeypatch.setattr(rehearsal, "_phase1_summary", lambda _environ: {"status": "passed"})
    monkeypatch.setattr(
        rehearsal,
        "_operator_stack_evidence",
        lambda **_kwargs: {"status": "passed"},
    )
    monkeypatch.setattr(rehearsal, "_event_read_path_evidence", lambda _environ: {"status": "passed"})
    monkeypatch.setattr(
        rehearsal,
        "_rollback_evidence",
        lambda _repository: {"status": "passed", "current_revision": revision, "previous_revision": "b" * 40},
    )

    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        harness_results={
            "status": "passed",
            "evidence_classification": "actual_executed",
            "paths_executed": 1,
            "all_paths_passed": True,
            "bit_identity_confirmed": True,
        },
        github_actions_job={
            "status": "completed",
            "runner_id": 3.7,
            "steps": [{"name": "pytest", "conclusion": "success"}],
            "conclusion": "success",
        },
        logs_available=True,
    )

    assert bundle.ci_evidence["state"] == "ci_unavailable"
    assert "ci_evidence_ci_unavailable" in bundle.blockers
    assert bundle.readiness_state == "ci_unavailable"
