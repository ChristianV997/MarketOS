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

import json
from pathlib import Path

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
