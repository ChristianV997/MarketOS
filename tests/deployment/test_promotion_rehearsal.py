"""Tests for deployment promotion rehearsal bundle.

Validates the 14 key requirements:
1. Local dry-run requires zero credentials.
2. Staging rejects weak or default passwords.
3. Production requirements remain explicit.
4. No live mutation can pass local or staging readiness.
5. Container static checks enforce non-root and healthcheck.
6. Malformed reports fail closed.
7. Zero-step CI remains ci_unavailable and is never passed.
8. Executed failures remain failed.
9. Replay hashes are deterministic across multiple runs.
10. Secret-shaped values are rejected or redacted.
11. Raw logs are never emitted into promotion bundles.
12. CoderOS unavailable is represented honestly.
13. Colab matrix results are reproducible and preserve zero-secret state.
14. Readiness bundle does not become a second quality gate.
"""

from __future__ import annotations

import ast
import json
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.deployment.promotion_fixtures import (
    fixture_coderos_unavailable,
    fixture_deterministic_replay_across_runs,
    fixture_failed_health_check,
    fixture_live_mutation_flag_accidentally_enabled,
    fixture_malformed_readiness_report,
    fixture_successful_offline_colab_matrix,
    fixture_weak_default_database_password,
    fixture_zero_step_ci,
)
from backend.deployment.promotion_rehearsal import (
    check_container_static_hardening,
    classify_ci_evidence,
    execute_promotion_rehearsal,
    redact_secrets,
)
from backend.deployment import promotion_rehearsal as rehearsal_module


def test_deployment_rehearsal_does_not_depend_on_script_layer() -> None:
    source_path = Path(__file__).resolve().parents[2] / "backend" / "deployment" / "promotion_rehearsal.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert "scripts.run_high_value_path_harness" not in imported_modules


def test_operator_harness_wrapper_delegates_to_canonical_module() -> None:
    from backend.deployment import high_value_path_harness
    import scripts.run_high_value_path_harness as operator_harness

    assert operator_harness.run_harness is high_value_path_harness.run_harness
    assert operator_harness.main is high_value_path_harness.main
    assert operator_harness.PATH_IDS == high_value_path_harness.PATH_IDS


def test_local_dry_run_requires_zero_credentials() -> None:
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
    )
    assert bundle.readiness_state == "ci_unavailable"
    assert "ci_evidence_ci_unavailable" in bundle.blockers
    assert bundle.credential_classification.get("no_credentials_required") is True
    assert bundle.high_value_path_summary["evidence_classification"] == "actual_executed"
    assert bundle.high_value_path_summary["status"] == "passed"


def test_local_execution_does_not_self_attest_release_readiness() -> None:
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        ci_override={"ci_status": "passed", "total_steps": 4, "runners_active": 1, "logs_available": True},
        harness_results={
            "status": "passed",
            "all_paths_passed": True,
            "paths_executed": 9,
            "bit_identity_confirmed": True,
            "evidence_classification": "actual_executed",
        },
    )
    assert bundle.ci_evidence["state"] == "passed"
    assert bundle.readiness_state != "passed"
    assert bundle.phase1_readiness["status"] == "blocked"
    assert bundle.operator_stack["status"] in {"unavailable", "not_run"}


def test_rehearsal_surfaces_are_sanitized_and_deterministic() -> None:
    first = execute_promotion_rehearsal(environment="local_dry_run", environ={})
    second = execute_promotion_rehearsal(environment="local_dry_run", environ={})
    assert first.deterministic_hash == second.deterministic_hash
    assert first.event_read_path["status"] == "unavailable"
    assert first.rollback_evidence["status"] == "passed"
    assert first.to_dict()["phase1_readiness"]["network_calls"] is False
    assert "CJ_API_KEY" not in json.dumps(first.to_dict())


@pytest.mark.parametrize("marker", ["stale", "partial"])
def test_stale_or_partial_local_evidence_cannot_pass(marker: str) -> None:
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        ci_override={"ci_status": "passed", "total_steps": 4, "runners_active": 1, "logs_available": True},
        harness_results={
            "status": "passed",
            "all_paths_passed": True,
            "paths_executed": 9,
            "evidence_classification": "actual_executed",
            marker: True,
        },
    )
    assert bundle.high_value_path_summary["status"] == "unavailable"
    assert bundle.readiness_state == "unavailable"


def test_malformed_event_read_path_fails_closed(tmp_path, monkeypatch) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    event_path = artifact_root / "events.jsonl"
    event_path.write_text('{"not_an_event": true}\n', encoding="utf-8")
    monkeypatch.setattr(rehearsal_module, "ROOT", tmp_path)
    result = rehearsal_module._event_read_path_evidence({"MARKETOS_EVENT_READ_JSONL_PATH": str(event_path)})
    assert result["status"] == "malformed"
    assert result["event_count"] == 0


def test_staging_rejects_weak_or_default_passwords() -> None:
    bundle = fixture_weak_default_database_password()
    assert bundle.readiness_state == "blocked"
    assert len(bundle.blockers) > 0
    blocker_str = " ".join(bundle.blockers)
    assert "insecure" in blocker_str or "weak" in blocker_str or "staging" in blocker_str


def test_production_requirements_remain_explicit() -> None:
    bundle = execute_promotion_rehearsal(
        environment="live_provider_blocked",
        environ={},
    )
    assert bundle.readiness_state == "blocked"
    assert len(bundle.blockers) > 0
    blocker_messages = " ".join(bundle.blockers)
    assert "DATABASE_URL" in blocker_messages or "ALLOWED_ORIGINS" in blocker_messages or "contract_" in blocker_messages


def test_live_mutation_flag_accidentally_enabled_blocks_staging() -> None:
    bundle = fixture_live_mutation_flag_accidentally_enabled()
    assert bundle.readiness_state == "blocked"
    blocker_str = " ".join(bundle.blockers)
    assert "live_mutations_forbidden" in blocker_str or "live_mutation" in blocker_str


def test_container_static_checks_enforce_non_root_and_healthcheck(tmp_path: Path) -> None:
    bad_dockerfile = tmp_path / "Dockerfile.insecure"
    bad_dockerfile.write_text("FROM python:3.11\nCMD [\"python\", \"app.py\"]\n", encoding="utf-8")

    findings = check_container_static_hardening(bad_dockerfile)
    assert findings["status"] == "failed"
    assert findings["non_root_user"] is False
    assert findings["healthcheck_present"] is False
    assert findings["stopsignal_present"] is False

    repo_root = Path(__file__).resolve().parents[2]
    real_dockerfile = repo_root / "Dockerfile"
    if real_dockerfile.exists():
        real_findings = check_container_static_hardening(real_dockerfile)
        assert real_findings["status"] == "passed"


def test_malformed_reports_fail_closed() -> None:
    report = fixture_malformed_readiness_report()
    assert report["status"] == "malformed"
    assert report["fail_closed"] is True


def test_zero_step_ci_classification() -> None:
    classification = classify_ci_evidence(
        ci_status="ci_unavailable",
        total_steps=0,
        runners_active=0,
        logs_available=False,
    )
    assert classification["state"] == "ci_unavailable"
    assert classification["state"] != "passed"

    bundle = fixture_zero_step_ci()
    assert bundle.ci_evidence["state"] in ("ci_unavailable", "unavailable")
    assert bundle.ci_evidence["state"] != "passed"


def test_executed_failure_and_timeout_are_not_erased_by_missing_logs() -> None:
    failed = classify_ci_evidence("failed", total_steps=3, runners_active=1, logs_available=False)
    timed_out = classify_ci_evidence("timed_out", total_steps=3, runners_active=1, logs_available=False)
    assert failed["state"] == "failed"
    assert timed_out["state"] == "timed_out"


def test_success_without_logs_remains_ci_unavailable() -> None:
    result = classify_ci_evidence("passed", total_steps=3, runners_active=1, logs_available=False)
    assert result["state"] == "ci_unavailable"


def test_executed_failures_remain_failed(tmp_path: Path) -> None:
    bundle = fixture_failed_health_check(tmp_path)
    assert bundle.readiness_state == "failed"
    assert len(bundle.blockers) > 0
    assert any("container_hardening" in b for b in bundle.blockers)


def test_deterministic_replay_across_runs() -> None:
    run1, run2 = fixture_deterministic_replay_across_runs()

    hash1 = run1.deterministic_hash
    hash2 = run2.deterministic_hash

    assert len(hash1) == 64
    assert hash1 == hash2, "Promotion rehearsal hashes must be bit-for-bit deterministic across runs"


def test_secret_shaped_values_are_redacted() -> None:
    db_k = "".join(["DATA", "BASE_URL"])
    jwt_k = "".join(["JWT", "_", "SECRET"])
    api_k = "".join(["API", "_", "KEY"])
    tok_k = "".join(["tok", "en"])

    leaky_dict = {
        db_k: "postgresql" + "://user:secret_pass@localhost:5432/db",
        jwt_k: "jwt" + "-dummy-token-value-12345",
        api_k: "sk" + "-live-123456789abcdef",
        "NORMAL_KEY": "marketos-local",
        "nested": {
            tok_k: "bearer" + " secret_sample_val",
            "safe": 12345,
        },
    }

    sanitized = redact_secrets(leaky_dict)

    assert sanitized[db_k] == "[REDACTED]"
    assert sanitized[jwt_k] == "[REDACTED]"
    assert sanitized[api_k] == "[REDACTED]"
    assert sanitized["NORMAL_KEY"] == "marketos-local"
    assert sanitized["nested"][tok_k] == "[REDACTED]"
    assert sanitized["nested"]["safe"] == 12345


def test_raw_logs_are_never_emitted_into_promotion_bundles() -> None:
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={"DATABASE_URL": "postgresql://user:pass@localhost:5432/db"},
    )
    bundle_json = json.dumps(bundle.to_dict())

    assert "my_super_secret" not in bundle_json
    assert "user:pass" not in bundle_json
    assert "Traceback (most recent call last)" not in bundle_json


def test_coderos_status_represented_honestly() -> None:
    bundle = fixture_coderos_unavailable()
    coderos_status = bundle.coderos_status
    assert coderos_status.get("status") in ("unavailable", "simulated", "offline")
    assert coderos_status.get("runtime_imports_allowed") is False


def test_colab_matrix_results_are_reproducible() -> None:
    colab_data = fixture_successful_offline_colab_matrix()
    assert colab_data.get("all_paths_passed") is True
    assert colab_data.get("bit_identity_confirmed") is True
    assert colab_data.get("status") == "passed"


def test_promotion_rehearsal_does_not_replace_quality_gate() -> None:
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
    )
    assert bundle.readiness_state != "passed"
    remediations_str = " ".join(bundle.remediations)
    assert "run_local_quality_gate.py" in remediations_str or "session_finish.py" in remediations_str or "uvicorn" in remediations_str


# ---------------------------------------------------------------------------
# Real GitHub Actions job evidence (runner_id=0, empty steps, unavailable
# logs) -- classify_github_actions_job is a pure adapter over the existing
# classify_ci_evidence(), not a second CI authority.
# ---------------------------------------------------------------------------


def test_classify_github_actions_job_treats_runner_id_zero_as_ci_unavailable() -> None:
    """A real GitHub Actions job response with runner_id=0 (never assigned
    a runner) and an empty steps list is the exact shape GitHub reports
    when a workflow never actually started -- this must classify as
    ci_unavailable, never as a passed or failed execution."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    result = classify_github_actions_job({"runner_id": 0, "steps": [], "status": "completed", "conclusion": None})
    assert result["state"] == "ci_unavailable"
    assert result["runner_id"] == 0
    assert result["steps_executed"] == 0
    assert result["runner_assigned"] is False


def test_classify_github_actions_job_treats_missing_job_as_unavailable() -> None:
    """job=None (the run/job could not be fetched at all -- API 404, no
    permissions, or the run doesn't exist) must fail closed to
    ci_unavailable, never be silently treated as zero real steps executed
    successfully."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    result = classify_github_actions_job(None)
    assert result["state"] == "ci_unavailable"
    assert result["runner_id"] is None
    assert "job_unavailable" in result["classification_reason"]


def test_classify_github_actions_job_preserves_an_executed_failure_with_a_real_runner() -> None:
    """A genuinely assigned runner (nonzero runner_id) with executed steps
    and a failure conclusion must remain 'failed' -- runner_id/steps
    evidence must never launder an executed failure into ci_unavailable."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    job = {
        "runner_id": 17,
        "steps": [{"name": "checkout", "conclusion": "success"}, {"name": "pytest", "conclusion": "failure"}],
        "status": "completed",
        "conclusion": "failure",
    }
    result = classify_github_actions_job(job, logs_available=True)
    assert result["state"] == "failed"
    assert result["runner_id"] == 17
    assert result["steps_executed"] == 2


def test_classify_github_actions_job_reports_unavailable_logs_even_with_a_passed_conclusion() -> None:
    """A run that executed and passed, but whose logs could not be fetched
    (e.g. expired/retention-deleted), must remain ci_unavailable -- a
    passed conclusion is not admissible evidence without logs to verify it."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    job = {"runner_id": 5, "steps": [{"name": "pytest", "conclusion": "success"}], "status": "completed", "conclusion": "success"}
    result = classify_github_actions_job(job, logs_available=False)
    assert result["state"] == "ci_unavailable"


def test_classify_github_actions_job_fails_closed_on_a_malformed_job() -> None:
    """A job value that is neither None nor a mapping (e.g. a raw string
    or list from a broken API response) must fail closed, not crash and
    not be silently treated as any particular CI state."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    result = classify_github_actions_job("not-a-job")
    assert result["state"] == "ci_unavailable"
    assert result["classification_reason"]


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting"])
def test_classify_github_actions_job_distinguishes_pending_from_permanently_unavailable(status: str) -> None:
    """A workflow that has not finished yet (status != "completed") is a
    distinct, deterministic state from a permanently missing/zero-step
    run: it may still produce real evidence, so it must be flagged
    pending=True rather than folded into the same ci_unavailable a truly
    dead run produces. GitHub only ever sets `conclusion` once the job
    reaches status="completed", so a `conclusion` value present alongside
    a non-completed status must not be trusted as real evidence either."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    result = classify_github_actions_job({"status": status, "runner_id": 42, "steps": [], "conclusion": None})
    assert result["state"] == "ci_unavailable"
    assert result["pending"] is True
    assert "job_pending" in result["classification_reason"]


def test_classify_github_actions_job_completed_status_is_not_pending() -> None:
    """The positive case for the pending guard: a genuinely completed job
    must never be flagged pending, even though pending defaults to a
    falsy-looking value elsewhere -- proving the guard is a real check,
    not a tautology."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    result = classify_github_actions_job({"status": "completed", "runner_id": 7, "steps": [{"name": "pytest", "conclusion": "success"}], "conclusion": "success"}, logs_available=True)
    assert result["pending"] is False
    assert result["state"] == "passed"


def test_classify_github_actions_job_treats_a_missing_steps_key_the_same_as_an_empty_list() -> None:
    """The docstring claims a missing `steps` key is handled the same as
    an empty list -- prove it with a job that omits the key entirely,
    not one that sets it to []."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    job = {"status": "completed", "runner_id": 3, "conclusion": None}
    assert "steps" not in job
    result = classify_github_actions_job(job)
    assert result["steps_executed"] == 0
    assert result["state"] == "ci_unavailable"


def test_classify_github_actions_job_rejects_an_implausible_negative_runner_id() -> None:
    """GitHub never reports a negative runner_id for real evidence; a
    negative value must not be trusted as proof a runner was assigned."""
    from backend.deployment.promotion_rehearsal import classify_github_actions_job

    result = classify_github_actions_job({"status": "completed", "runner_id": -1, "steps": [{"name": "pytest", "conclusion": "success"}], "conclusion": "success"})
    assert result["runner_id"] == 0
    assert result["runner_assigned"] is False
    assert result["state"] == "ci_unavailable"


def test_execute_promotion_rehearsal_wires_real_github_actions_job_evidence_end_to_end() -> None:
    """The production entrypoint, not just the adapter in isolation: a
    real runner_id=0/steps=[] job must (1) drive ci_evidence to
    ci_unavailable, (2) appear in the resulting blockers, and (3) surface
    a concrete, non-empty administrator-facing diagnostic identifying the
    exact runner/log evidence gap -- not merely a generic 'blocked'
    status with no explanation of what evidence was missing."""
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        github_actions_job={"runner_id": 0, "steps": [], "status": "completed", "conclusion": None},
    )
    assert bundle.ci_evidence["state"] == "ci_unavailable"
    assert any("ci_evidence_ci_unavailable" in b for b in bundle.blockers)
    diagnostic = bundle.ci_admissibility_diagnostic
    assert diagnostic["failure_details"]["runner_id"] == 0
    assert diagnostic["status"] == "detected"
    assert diagnostic["message"]


def test_execute_promotion_rehearsal_github_actions_job_takes_precedence_over_ci_override() -> None:
    """Supplying both github_actions_job and ci_override is ambiguous --
    github_actions_job (the more specific, real-evidence-shaped input)
    must win deterministically, not silently pick whichever happens to be
    evaluated last."""
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        ci_override={"ci_status": "passed", "total_steps": 4, "runners_active": 1, "logs_available": True},
        github_actions_job={"runner_id": 0, "steps": [], "status": "completed", "conclusion": None},
    )
    assert bundle.ci_evidence["state"] == "ci_unavailable"


def test_execute_promotion_rehearsal_assigned_runner_with_verified_logs_does_not_block_on_ci() -> None:
    """The positive case: a real, assigned runner with executed passing
    steps and available logs must not itself add a ci_evidence blocker --
    proving the wiring is not a one-way always-block shortcut."""
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        github_actions_job={"runner_id": 9001, "steps": [{"name": "pytest", "conclusion": "success"}], "status": "completed", "conclusion": "success"},
        logs_available=True,
    )
    assert bundle.ci_evidence["state"] == "passed"
    assert not any(b.startswith("ci_evidence_") for b in bundle.blockers)


def test_execute_promotion_rehearsal_ci_admissibility_diagnostic_reflects_the_ci_override_path_too() -> None:
    """The wiring is not exclusive to github_actions_job -- the abstract
    ci_override path (the pre-existing call shape) must also produce an
    accurate ci_admissibility_diagnostic, not just the default all-defaults
    diagnostic every other call shape used to fall back to."""
    bundle = execute_promotion_rehearsal(
        environment="local_dry_run",
        environ={},
        ci_override={"ci_status": "ci_unavailable", "total_steps": 0, "runners_active": 0, "logs_available": False},
    )
    diagnostic = bundle.ci_admissibility_diagnostic
    assert diagnostic["status"] == "detected"
    assert diagnostic["failure_details"]["steps_executed"] == 0
    assert diagnostic["failure_details"]["runner_id"] is None


# ---------------------------------------------------------------------------
# Operator-stack evidence: _operator_stack_evidence now actually invokes
# #290's existing scripts/run_local_operator_stack.py (bounded, opt-in for
# --execute) instead of only checking whether the file exists. subprocess.run
# is mocked here because the runner script itself is #290's exclusive file
# and is not present on this branch -- these tests prove this module's own
# invocation/parsing/redaction logic is correct against the runner's real,
# directly-observed JSON contract (schema MarketOS.LocalOperatorStack.v1),
# captured by actually running that script with --execute --backend-only in
# a separate inspection worktree of #290's branch before writing this code.
# ---------------------------------------------------------------------------


def _fake_operator_stack_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "schema": "MarketOS.LocalOperatorStack.v1",
        "classification": "passed",
        "dry_run": False,
        "mode": "fixture_only",
        "external_network_calls": False,
        "mutated": False,
        "surfaces": [
            {"name": "health", "plane": "api", "classification": "passed", "http_status": 200, "reason": None},
            {"name": "ready", "plane": "api", "classification": "passed", "http_status": 200, "reason": None},
            {"name": "workbench_api", "plane": "api", "classification": "surface_absent", "http_status": 404, "reason": None},
        ],
        "logs": {"backend": "INFO: Uvicorn running on http://127.0.0.1:3000\n"},
    }
    payload.update(overrides)
    return payload


def test_operator_stack_evidence_reports_installed_runner_as_read_only() -> None:
    """The installed runner is available, but default rehearsal stays dry-run."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    result = _operator_stack_evidence()
    assert result["status"] == "not_run"
    assert result["runner_present"] is True
    assert result["dry_run"] is True
    assert result["network_calls"] is False
    assert result["mutated"] is False


class _FakePopen:
    """Stand-in for subprocess.Popen supporting the exact interface
    _operator_stack_evidence and _terminate_operator_stack_process use:
    communicate(timeout=), poll(), pid, returncode, kill(), send_signal().
    ``communicate_results`` is a sequence consumed one per communicate()
    call -- either an ``(stdout, stderr)`` tuple (the process has now
    exited) or an ``Exception`` instance to raise (e.g. TimeoutExpired),
    letting a test simulate "first call times out, second call (after a
    signal) succeeds"."""

    def __init__(self, communicate_results: list[Any], *, pid: int = 4242, returncode: int = 0) -> None:
        self._results = list(communicate_results)
        self.pid = pid
        self.returncode = returncode
        self._exited = False
        self.signals_received: list[Any] = []

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        result = self._results.pop(0)
        if isinstance(result, Exception):
            if not isinstance(result, subprocess.TimeoutExpired):
                # Real subprocess.Popen.communicate() only decodes after
                # it has already collected all output and reaped the
                # process -- a decode failure means the process is
                # already gone, unlike TimeoutExpired (still running).
                self._exited = True
            raise result
        self._exited = True
        return result

    def poll(self) -> int | None:
        return self.returncode if self._exited else None

    def kill(self) -> None:
        self.signals_received.append("SIGKILL")
        self._exited = True

    def send_signal(self, sig: Any) -> None:
        self.signals_received.append(sig)


def _with_fake_runner_present(monkeypatch: pytest.MonkeyPatch, fake_popen_factory) -> None:
    """Simulate #290's runner file existing on this branch, without
    affecting any other Path.is_file() check this module or its callees
    make for an unrelated path (e.g. the Dockerfile check, phase1's own
    file reads), and without intercepting any other subprocess.Popen/.run
    call the same pipeline makes for something else entirely
    (get_runtime_versions' own node/docker --version calls, and --
    confirmed by direct reproduction -- CPython's platform.platform()
    itself shells out on this interpreter/platform). fake_popen_factory
    is only invoked for argv that actually names the operator-stack
    runner script; anything else goes to the real subprocess.Popen/.run
    unmodified. Also patches os.killpg/os.getpgid to no-ops on POSIX
    (there is no real process group to signal) while still recording
    what _terminate_operator_stack_process attempted, via the fake
    Popen's own send_signal/kill tracking for the POSIX branch's
    process.kill() fallback and a module-level killpg spy."""
    runner_path = rehearsal_module.ROOT / "scripts" / "run_local_operator_stack.py"
    real_is_file = Path.is_file
    real_popen = rehearsal_module.subprocess.Popen
    killpg_calls: list[Any] = []

    def fake_is_file(self: Path) -> bool:
        if self == runner_path:
            return True
        return real_is_file(self)

    def scoped_popen(argv, *args, **kwargs):
        if isinstance(argv, (list, tuple)) and any(str(runner_path) in str(item) for item in argv):
            return fake_popen_factory(argv, **kwargs)
        return real_popen(argv, *args, **kwargs)

    def fake_killpg(pgid: int, sig: Any) -> None:
        killpg_calls.append((pgid, sig))

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.setattr(rehearsal_module.subprocess, "Popen", scoped_popen)
    monkeypatch.setattr(rehearsal_module.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(rehearsal_module.os, "killpg", fake_killpg, raising=False)
    return killpg_calls


def test_operator_stack_evidence_surfaces_a_real_passing_run_without_raw_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real, successful runner invocation must surface its classification
    and a sanitized surfaces summary -- and must NEVER include the runner's
    own raw `logs` field (a real captured stdout/stderr, up to and
    including process tracebacks), matching this bundle's existing,
    binding "no raw logs" invariant."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    payload = _fake_operator_stack_payload()
    seen_argv = []

    def fake_popen_factory(argv, **kwargs):
        seen_argv.append(list(argv))
        return _FakePopen([(json.dumps(payload), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert "--dry-run" in seen_argv[0]
    assert "--backend-only" in seen_argv[0]
    assert result["status"] == "passed"
    assert result["runner_present"] is True
    assert result["surfaces"][0]["name"] == "health"
    assert "logs" not in result
    assert "Uvicorn running" not in json.dumps(result)


def test_operator_stack_evidence_surfaces_partial_without_erasing_it_to_passed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real run.py where health/ready pass but a route is surface_absent
    reports "partial" -- must not be silently upgraded to "passed"."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    payload = _fake_operator_stack_payload(classification="partial")

    def fake_popen_factory(argv, **kwargs):
        return _FakePopen([(json.dumps(payload), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert result["status"] == "partial"


def test_operator_stack_evidence_execute_flag_selects_the_runners_execute_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """execute=True must pass --execute, never --dry-run, to the runner --
    proving the opt-in flag actually changes what gets invoked."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    seen_argv = []

    def fake_popen_factory(argv, **kwargs):
        seen_argv.append(list(argv))
        return _FakePopen([(json.dumps(_fake_operator_stack_payload()), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    _operator_stack_evidence(execute=True)
    assert "--execute" in seen_argv[0]
    assert "--dry-run" not in seen_argv[0]


def test_operator_stack_evidence_execute_flag_false_selects_frontend_probe_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """backend_only=False must omit --backend-only, so the runner also
    probes the cockpit/workbench UI routes -- the flag genuinely changes
    the invoked argv, not just documented as an option."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    seen_argv = []

    def fake_popen_factory(argv, **kwargs):
        seen_argv.append(list(argv))
        return _FakePopen([(json.dumps(_fake_operator_stack_payload()), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    _operator_stack_evidence(backend_only=False)
    assert "--backend-only" not in seen_argv[0]


def test_operator_stack_evidence_times_out_bounded_and_attempts_graceful_interrupt_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hung runner must fail closed to timed_out within the caller's
    own bound, never hang the whole promotion rehearsal indefinitely --
    and the termination path must attempt a graceful interrupt (matching
    how #290's own runner documents cleaning up "on interrupt") before
    any hard kill, giving its own child-process cleanup a real chance to
    run rather than being silently skipped."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    fake_process = _FakePopen(
        [subprocess.TimeoutExpired(cmd=["fake"], timeout=5.0), ("", "")]  # 2nd communicate(): the graceful wait succeeds
    )

    def fake_popen_factory(argv, **kwargs):
        return fake_process

    killpg_calls = _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence(timeout_s=5.0)
    assert result["status"] == "timed_out"
    assert "5" in result["reason"]
    if sys.platform != "win32":
        # First signal sent must be the graceful one (SIGINT), not SIGKILL.
        assert killpg_calls[0][1] == signal.SIGINT
        # The process exited on the graceful attempt (2nd communicate()
        # succeeded), so no SIGKILL escalation should have been needed.
        assert all(sig != signal.SIGKILL for _pgid, sig in killpg_calls)


def test_operator_stack_evidence_escalates_to_kill_when_graceful_interrupt_does_not_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the runner does not exit even after the graceful interrupt
    (fully hung, not just slow), the caller must still escalate to a
    hard kill rather than hanging forever waiting for it."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    fake_process = _FakePopen(
        [
            subprocess.TimeoutExpired(cmd=["fake"], timeout=5.0),  # initial wait
            subprocess.TimeoutExpired(cmd=["fake"], timeout=10.0),  # graceful grace period also times out
            ("", ""),  # final reap after the hard kill succeeds
        ]
    )

    def fake_popen_factory(argv, **kwargs):
        return fake_process

    killpg_calls = _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence(timeout_s=5.0)
    assert result["status"] == "timed_out"
    if sys.platform != "win32":
        assert killpg_calls[0][1] == signal.SIGINT
        assert killpg_calls[-1][1] == signal.SIGKILL


def test_operator_stack_evidence_fails_closed_on_undecodable_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """A child that writes bytes text=True cannot decode must fail closed
    to malformed rather than let UnicodeDecodeError (a ValueError
    subclass) propagate uncaught out of this function."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    fake_process = _FakePopen([UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")])

    def fake_popen_factory(argv, **kwargs):
        return fake_process

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert result["status"] == "malformed"
    assert "undecodable" in result["reason"]


def test_operator_stack_evidence_fails_closed_on_malformed_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-JSON stdout (a crashed runner, truncated output) must fail
    closed to malformed, never be silently treated as any real status."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    def fake_popen_factory(argv, **kwargs):
        return _FakePopen([("not json at all", "")], returncode=1)

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert result["status"] == "malformed"


def test_operator_stack_evidence_fails_closed_on_wrong_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    """Valid JSON but the wrong schema (a different tool's output landed
    on stdout somehow) must fail closed, never be trusted as this
    runner's real evidence."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    def fake_popen_factory(argv, **kwargs):
        return _FakePopen([(json.dumps({"schema": "SomeOther.Schema.v1", "classification": "passed"}), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert result["status"] == "malformed"


def test_operator_stack_evidence_fails_closed_on_empty_classification(monkeypatch: pytest.MonkeyPatch) -> None:
    """A schema-matching payload whose classification is empty/non-string
    (a genuinely malformed but schema-valid runner report) must still
    fail closed to malformed, not pass an empty string through as a
    "status"."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    payload = _fake_operator_stack_payload(classification="")

    def fake_popen_factory(argv, **kwargs):
        return _FakePopen([(json.dumps(payload), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert result["status"] == "malformed"


def test_operator_stack_evidence_ignores_non_mapping_surface_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed surfaces list containing a non-dict entry must not
    crash the summary -- the malformed entry is skipped, not trusted."""
    from backend.deployment.promotion_rehearsal import _operator_stack_evidence

    payload = _fake_operator_stack_payload(surfaces=["not-a-dict", {"name": "health", "plane": "api", "classification": "passed", "http_status": 200, "reason": None}])

    def fake_popen_factory(argv, **kwargs):
        return _FakePopen([(json.dumps(payload), "")])

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    result = _operator_stack_evidence()
    assert len(result["surfaces"]) == 1
    assert result["surfaces"][0]["name"] == "health"


def test_execute_promotion_rehearsal_operator_stack_wiring_and_no_raw_logs_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """The production entrypoint, not just the helper in isolation: real
    operator-stack evidence must reach the bundle's operator_stack field,
    and the full bundle (every field, not only operator_stack) must still
    never contain the runner's raw logs -- extending the pre-existing
    raw-logs invariant to this new evidence source."""
    payload = _fake_operator_stack_payload(classification="failed", logs={"backend": "Traceback (most recent call last):\n  raise RuntimeError('boom')\n"})

    def fake_popen_factory(argv, **kwargs):
        return _FakePopen([(json.dumps(payload), "")], returncode=1)

    _with_fake_runner_present(monkeypatch, fake_popen_factory)
    bundle = execute_promotion_rehearsal(environment="local_dry_run", environ={}, execute_operator_stack=True)
    assert bundle.operator_stack["status"] == "failed"
    bundle_json = json.dumps(bundle.to_dict())
    assert "Traceback" not in bundle_json
    assert "boom" not in bundle_json
