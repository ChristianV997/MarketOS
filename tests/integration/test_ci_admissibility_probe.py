from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ai.ci_admissibility_probe import (
    CANONICAL_INPUT_SCHEMA,
    INPUT_SCHEMA,
    MAX_INPUT_BYTES,
    REPORT_SCHEMA,
    EvidenceInputError,
    build_report,
    load_input,
    render_json,
    render_markdown,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "ci_admissibility"
HEAD = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
BASE = "df160af1aad615dcdee7934bcd7122898eb5eff1"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def payload() -> dict:
    return fixture("ci_state_matrix.json")


def job(data: dict) -> dict:
    return data["jobs"][0]


def policy_digest(policy: dict) -> str:
    value = {"jobs": sorted(policy["jobs"]), "revision": policy["revision"]}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def report(data: dict | None = None) -> dict:
    return build_report(payload() if data is None else data)


def test_schema_and_success_require_bound_workflow_execution():
    result = report()
    assert result["schema"] == REPORT_SCHEMA
    assert result["source_schema"] == INPUT_SCHEMA
    assert result["classification"] == "pass"
    assert result["status"] == "passed"
    assert result["diagnostic_state"] == "pass"
    assert result["jobs"][0]["classification"] == "pass"
    assert result["jobs"][0]["runner_assigned"] is True
    assert result["jobs"][0]["steps_executed"] == 4
    assert result["admissible_evidence"] is True


def test_unbound_required_check_cannot_admit_bound_job_from_another_run():
    """A check without accepted identity fields cannot attest to run 42."""
    data = payload()
    data["checks"] = [
        {
            "name": "test",
            "kind": "ci",
            "status": "completed",
            "conclusion": "success",
        }
    ]

    result = report(data)

    assert result["classification"] == "ci_unavailable"
    assert result["admissible_evidence"] is False
    assert result["required_checks"] == [
        {
            "classification": "unbound_check_metadata",
            "conclusion": "success",
            "identity_classification": "unbound",
            "name": "test",
            "status": "completed",
        }
    ]
    assert result["diagnostic_state"] == "unbound_check_metadata"


def test_job_run_mismatch_is_rejected_even_when_workflow_is_successful():
    data = payload()
    data["jobs"][0]["run_id"] = 43

    result = report(data)

    assert result["classification"] == "ci_unavailable"
    assert result["jobs"][0]["identity_classification"] == "stale_job_metadata"
    assert result["admissible_evidence"] is False


def test_fixture_catalog_covers_required_admissibility_states():
    catalog = fixture("state_catalog.json")
    names = {item["name"] for item in catalog["cases"]}
    assert names == {
        "zero_step_runnerless",
        "executed_failure_logs",
        "executed_timeout",
        "executed_success",
        "success_missing_logs",
        "failure_logs_404",
        "pending_job",
        "deploy_preview_non_ci",
        "stale_job_metadata",
        "missing_workflow_context",
        "mixed_jobs",
    }


def test_zero_steps_runnerless_never_becomes_pass_or_executed_failure():
    data = payload()
    item = job(data)
    item.update(
        {
            "conclusion": "failure",
            "runner_id": 0,
            "runner_name": None,
            "steps_executed": 0,
            "log_status": "unavailable",
            "required_check_status": "failure",
        }
    )
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "zero_step_runnerless"
    assert result["jobs"][0]["classification"] == "zero_step_runnerless"
    assert result["jobs"][0]["status"] == "unavailable"
    assert result["admissible_evidence"] is False


def test_zero_step_workflow_failure_stays_unavailable():
    data = payload()
    data["workflow"]["conclusion"] = "failure"
    item = job(data)
    item.update(
        {
            "conclusion": "failure",
            "runner_id": 0,
            "runner_name": None,
            "steps_executed": 0,
            "log_status": "unavailable",
            "required_check_status": "failure",
        }
    )
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["jobs"][0]["classification"] == "zero_step_runnerless"
    assert "executed_failure" not in result["diagnostic_states"]


def test_executed_failure_with_logs_is_a_real_failure():
    data = payload()
    data["workflow"]["conclusion"] = "failure"
    item = job(data)
    item.update({"conclusion": "failure", "required_check_status": "failure", "steps_executed": 4})
    result = report(data)
    assert result["classification"] == "executed_failure"
    assert result["status"] == "failed"
    assert result["jobs"][0]["classification"] == "executed_failure"
    assert result["jobs"][0]["log_status"] == "available"
    assert "ci_unavailable" not in result["diagnostic_states"]


def test_executed_failure_with_404_logs_preserves_failure_and_log_gap():
    data = payload()
    data["workflow"]["conclusion"] = "failure"
    item = job(data)
    item.update(
        {
            "conclusion": "failure",
            "required_check_status": "failure",
            "log_status": "not_found",
            "log_http_status": 404,
        }
    )
    result = report(data)
    assert result["classification"] == "executed_failure"
    assert result["jobs"][0]["classification"] == "executed_failure"
    assert result["jobs"][0]["log_status"] == "not_found"


def test_timeout_is_distinct_from_failure():
    data = payload()
    data["workflow"]["conclusion"] = "timed_out"
    item = job(data)
    item.update({"conclusion": "timed_out", "required_check_status": "timed_out"})
    result = report(data)
    assert result["classification"] == "timed_out"
    assert result["status"] == "timed_out"
    assert result["jobs"][0]["classification"] == "timed_out"


def test_success_without_retrievable_logs_is_unavailable():
    data = payload()
    item = job(data)
    item.update({"log_status": "not_found", "log_http_status": 404})
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["jobs"][0]["classification"] == "unavailable_logs"
    assert result["jobs"][0]["status"] == "unavailable"


def test_pending_job_is_not_passed():
    data = payload()
    data["workflow"].update({"status": "in_progress", "conclusion": "pending"})
    item = job(data)
    item.update(
        {
            "status": "queued",
            "conclusion": "pending",
            "runner_id": None,
            "runner_name": None,
            "steps_executed": 0,
            "log_status": "not_queried",
            "required_check_status": "pending",
        }
    )
    result = report(data)
    assert result["classification"] == "pending"
    assert result["status"] == "pending"
    assert result["jobs"][0]["classification"] == "pending"


def test_diagnostic_state_never_reports_pass_when_classification_is_not_pass():
    # Every required job can individually classify as "pass" (nothing gets
    # added to the internal per-job `states` list) while the workflow's own
    # conclusion never reached "success" -- e.g. "neutral". The overall
    # classification correctly falls back to ci_unavailable, but a stale
    # unconditional "if not states: states.append('pass')" fallback used to
    # report diagnostic_state: "pass" anyway, even though admissible_evidence
    # and classification were both correctly False/ci_unavailable. A
    # consumer reading only diagnostic_state (not classification) could be
    # misled into treating this as clean evidence.
    data = payload()
    data["workflow"]["conclusion"] = "neutral"
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["status"] == "unavailable"
    assert result["admissible_evidence"] is False
    assert result["diagnostic_state"] != "pass"
    assert "pass" not in result["diagnostic_states"]


def test_deploy_preview_failure_is_not_ci_failure():
    data = payload()
    data["checks"] = [
        {
            "name": "netlify/deploy-preview",
            "kind": "deploy_preview",
            "status": "completed",
            "conclusion": "failure",
            "url": "https://deploy.example/preview/42",
        }
    ]
    result = report(data)
    assert result["classification"] == "pass"
    assert result["non_ci_checks"][0]["kind"] == "deploy_preview"
    assert result["non_ci_checks"][0]["conclusion"] == "failure"


def test_a_netlify_named_job_cannot_be_smuggled_in_as_a_passing_ci_job():
    # _normalize_check reclassifies a netlify/deploy-preview-named entry to
    # kind="deploy_preview" even when the caller declares kind="ci". A
    # jobs[] entry had no equivalent reclassification, so a caller could
    # declare kind="ci" on a Netlify-named job and have it reported as a
    # genuine passing CI job (status "passed", classification "pass"),
    # even though it can never be forced into required_jobs (which already
    # rejects deploy-preview-marker names).
    data = payload()
    data["jobs"].append(
        {
            "name": "Netlify - Header rules",
            "kind": "ci",
            "required": False,
            "status": "completed",
            "conclusion": "success",
            "head_sha": data["candidate_head_sha"],
            "run_id": 42,
            "workflow_name": "CI",
            "runner_id": 999,
            "steps_executed": 1,
            "log_status": "available",
            "required_check_status": "success",
        }
    )
    result = report(data)
    netlify_job = next(item for item in result["jobs"] if item["name"] == "Netlify - Header rules")
    assert netlify_job["status"] == "not_ci"
    assert netlify_job["classification"] == "not_ci"
    assert result["classification"] == "pass"


def test_stale_job_head_is_unavailable_not_candidate_pass():
    data = payload()
    job(data)["head_sha"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "stale_job_metadata"
    assert result["jobs"][0]["classification"] == "stale_metadata"
    assert result["jobs"][0]["identity_classification"] == "stale_job_metadata"


def test_target_binding_mismatch_is_stale_worktree_metadata():
    data = payload()
    data["target_head_sha"] = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "mixed"
    assert "stale_worktree_metadata" in result["diagnostic_states"]
    assert "stale_job_metadata" in result["diagnostic_states"]
    assert result["context_classification"] == "stale_worktree_metadata"
    assert result["jobs"][0]["classification"] == "stale_metadata"


def test_caller_cannot_claim_canonical_compatibility_mode():
    data = payload()
    data["canonical_input"] = True
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["source_schema"] == "unknown"
    assert result["error"] == "unknown_or_forbidden_field"


def test_binding_and_policy_provenance_are_reported_and_fingerprinted():
    first = report()
    assert first["target_head_sha"] == HEAD
    assert first["target_base_sha"] == BASE
    assert first["required_policy"]["source"] == "repository_policy"
    changed = payload()
    changed["required_policy"]["revision"] = "ci-policy-v2"
    changed["required_policy"]["fingerprint"] = policy_digest(changed["required_policy"])
    second = report(changed)
    assert second["required_policy"]["revision"] == "ci-policy-v2"
    assert first["fingerprint"] != second["fingerprint"]

    malformed = payload()
    malformed["required_policy"]["fingerprint"] = "0" * 64
    malformed_result = report(malformed)
    assert malformed_result["classification"] == "malformed"
    assert malformed_result["error"] == "required_policy_fingerprint_mismatch"


def test_workflow_not_created_is_distinct_from_a_completed_failure():
    data = payload()
    data["workflow"] = {
        "name": "CI",
        "run_id": None,
        "status": "not_created",
        "conclusion": None,
        "head_sha": None,
        "base_sha": None,
        "created_at": "2026-09-22T08:00:00+00:00",
        "updated_at": "2026-09-22T08:00:00+00:00",
    }
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "workflow_never_created"
    assert result["jobs"][0]["classification"] == "workflow_never_created"


def test_not_created_job_with_success_cannot_be_admitted_without_run_identity():
    data = payload()
    data["jobs"][0].update(
        {
            "status": "not_created",
            "conclusion": "success",
            "run_id": None,
            "workflow_name": None,
        }
    )
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "workflow_never_created"
    assert result["jobs"][0]["classification"] == "workflow_never_created"


def test_workflow_context_is_required_to_admit_success():
    data = payload()
    data["workflow"] = None
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "missing_workflow_context"
    assert result["jobs"][0]["classification"] == "missing_workflow_context"
    assert result["jobs"][0]["execution_classification"] == "pass"


def test_missing_required_job_is_unavailable():
    data = payload()
    data["required_jobs"] = ["test", "semgrep-policy"]
    data["required_policy"]["jobs"] = ["test", "semgrep-policy"]
    data["required_policy"]["fingerprint"] = policy_digest(data["required_policy"])
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["missing_required_jobs"] == ["semgrep-policy"]
    missing = next(item for item in result["jobs"] if item["name"] == "semgrep-policy")
    assert missing["classification"] == "required_job_missing"


def test_mixed_failure_pending_and_zero_step_preserve_each_state():
    data = payload()
    data["workflow"]["conclusion"] = "failure"
    data["required_jobs"] = ["test", "quality", "container"]
    data["required_policy"]["jobs"] = ["test", "quality", "container"]
    data["required_policy"]["fingerprint"] = policy_digest(data["required_policy"])
    first = job(data)
    first.update({"conclusion": "failure", "required_check_status": "failure"})
    data["jobs"] = [
        first,
        {
            "name": "quality",
            "required": True,
            "status": "queued",
            "conclusion": "pending",
            "head_sha": HEAD,
            "run_id": 42,
            "workflow_name": "CI",
            "runner_id": None,
            "steps_executed": 0,
            "log_status": "not_queried",
            "required_check_status": "pending",
        },
        {
            "name": "container",
            "required": True,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": HEAD,
            "run_id": 42,
            "workflow_name": "CI",
            "runner_id": 0,
            "steps_executed": 0,
            "log_status": "unavailable",
            "required_check_status": "failure",
        },
    ]
    result = report(data)
    states = {item["name"]: item["classification"] for item in result["jobs"]}
    assert result["classification"] == "executed_failure"
    assert states == {"container": "zero_step_runnerless", "quality": "pending", "test": "executed_failure"}
    assert set(result["diagnostic_states"]) == {"executed_failure", "pending", "zero_step_runnerless"}


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_required_ci_check_failure_or_cancellation_affects_verdict(conclusion: str):
    data = payload()
    data["checks"] = [{"name": "test", "kind": "ci", "status": "completed", "conclusion": conclusion}]
    result = report(data)
    assert result["classification"] == "executed_failure"
    assert result["admissible_evidence"] is False


@pytest.mark.parametrize("step_status", ["skipped", "failure", "cancelled"])
def test_non_success_step_status_cannot_be_counted_as_success(step_status: str):
    data = payload()
    item = job(data)
    item.pop("steps_executed")
    item["steps"] = [{"name": "checkout", "status": step_status}]
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["jobs"][0]["classification"] == "incomplete_steps"
    assert result["jobs"][0]["steps_executed"] == 1


@pytest.mark.parametrize(
    "workflow_name",
    ["Netlify Deploy Preview", "deploy   preview", "DEPLOY\u2011PREVIEW"],
)
def test_non_ci_workflow_name_variants_cannot_admit_ci(workflow_name: str):
    data = payload()
    data["workflow"]["name"] = workflow_name
    result = report(data)
    assert result["classification"] == "ci_unavailable"
    assert result["context_classification"] == "non_ci_workflow"
    assert result["admissible_evidence"] is False


@pytest.mark.parametrize("job_name", ["Deploy Preview", "deploy   preview", "DEPLOY\u2011PREVIEW"])
def test_non_ci_job_name_variants_are_rejected_from_required_policy(job_name: str):
    data = payload()
    data["required_jobs"] = [job_name]
    data["required_policy"]["jobs"] = [job_name]
    data["required_policy"]["fingerprint"] = policy_digest(data["required_policy"])
    data["jobs"][0]["name"] = job_name
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "non_ci_check_in_required_jobs"


@pytest.mark.parametrize("required_check_status", [[], {}, 1, True])
def test_malformed_required_check_status_returns_structured_error(required_check_status):
    data = payload()
    data["jobs"][0]["required_check_status"] = required_check_status
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "invalid_required_check_status"


def test_canonical_cievidence_is_accepted_but_missing_context_stays_visible():
    result = build_report(fixture("canonical_cievidence.json"))
    assert result["source_schema"] == CANONICAL_INPUT_SCHEMA
    assert result["classification"] == "ci_unavailable"
    assert result["diagnostic_state"] == "missing_workflow_context"
    assert result["admissible_evidence"] is False


def test_raw_log_fields_are_malformed_without_echoing_input():
    data = fixture("malformed_raw_logs.json")
    result = build_report(data)
    serialized = json.dumps(result, sort_keys=True)
    assert result["classification"] == "malformed"
    assert result["diagnostic_state"] == "malformed_metadata"
    assert "fixture placeholder" not in serialized


def test_unknown_fields_and_duplicate_jobs_fail_closed():
    data = payload()
    data["jobs"].append(copy.deepcopy(data["jobs"][0]))
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "duplicate_job_name"

    data = payload()
    data["jobs"][0]["private_notes"] = "not retained"
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "unknown_or_forbidden_field"


def test_required_flag_mismatch_and_non_ci_required_job_are_rejected():
    data = payload()
    data["jobs"][0]["required"] = False
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "job_required_flag_mismatch"

    data = payload()
    data["required_jobs"] = ["netlify/deploy-preview"]
    data["required_policy"]["jobs"] = ["netlify/deploy-preview"]
    data["required_policy"]["fingerprint"] = policy_digest(data["required_policy"])
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "non_ci_check_in_required_jobs"


def test_contradictory_pending_and_log_metadata_are_rejected():
    data = payload()
    data["jobs"][0].update({"status": "queued", "conclusion": "failure"})
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "contradictory_pending_job_metadata"

    data = payload()
    data["jobs"][0].update({"log_status": "available", "log_http_status": 404})
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "contradictory_log_metadata"


def test_missing_rich_job_workflow_binding_cannot_admit_success():
    data = payload()
    data["jobs"][0].pop("run_id")
    data["jobs"][0].pop("workflow_name")
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "missing_job_workflow_identity"


def test_logs_available_flag_must_match_log_status():
    data = payload()
    data["jobs"][0].update({"logs_available": False, "log_status": "available", "log_http_status": 200})
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "contradictory_log_metadata"


def test_pending_job_and_check_states_cannot_claim_completed_evidence():
    data = payload()
    data["jobs"][0].update({"status": "queued", "conclusion": "pending", "required_check_status": "failure", "runner_id": None, "steps_executed": 0, "log_status": "not_queried"})
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "contradictory_pending_job_metadata"

    data = payload()
    data["checks"] = [{"name": "ci-check", "kind": "ci", "status": "queued", "conclusion": "failure"}]
    result = report(data)
    assert result["classification"] == "malformed"
    assert result["error"] == "contradictory_pending_check_metadata"


def test_credential_bearing_urls_are_redacted():
    data = payload()
    data["checks"] = [
        {
            "name": "deploy-preview",
            "kind": "deploy_preview",
            "status": "completed",
            "conclusion": "failure",
            "url": "https://operator:" + ("pw" * 8) + "@deploy.example/preview?" + "to" + "ken" + "=" + ("x" * 20),
        }
    ]
    result = report(data)
    serialized = json.dumps(result, sort_keys=True)
    assert result["redacted_url_count"] == 1
    assert "operator:" not in serialized
    assert "pwpwpwpwpwpwpwpw" not in serialized
    assert "deploy.example" not in serialized
    assert "[redacted-url]" in serialized

    for unsafe_url in (
        "https://deploy.example/ci?access%5F" + "token" + "=LEAKVALUE123456",
        "https://deploy.example/ci?x-api-" + "key" + "=LEAKVALUE123456",
        "https://deploy.example/run/" + "token" + "/LEAKVALUE123456",
    ):
        candidate = payload()
        candidate["checks"] = [
            {
                "name": "deploy-preview",
                "kind": "deploy_preview",
                "status": "completed",
                "conclusion": "failure",
                "url": unsafe_url,
            }
        ]
        sanitized = report(candidate)
        serialized = json.dumps(sanitized, sort_keys=True)
        assert sanitized["redacted_url_count"] == 1
        assert "LEAKVALUE123456" not in serialized
        assert "[redacted-url]" in serialized


@pytest.mark.parametrize(
    "value",
    [
        "https://operator:" + ("pw" * 8) + "@example.test/ci",
        "mysql://operator:" + ("pw" * 8) + "@db.example.test/ci",
        "gho_" + ("x" * 24),
        "AKIA" + ("A" * 16),
        "AIza" + ("x" * 24),
        "sk-" + ("x" * 24),
    ],
)
def test_secret_shaped_metadata_is_rejected_without_echo(value: str):
    data = payload()
    data["repository"] = value
    result = report(data)
    serialized = json.dumps(result, sort_keys=True)
    assert result["classification"] == "malformed"
    assert value not in serialized


def test_direct_payload_size_and_nesting_are_bounded():
    oversized = payload()
    oversized["checks"] = [
        {
            "name": f"check-{index}-" + ("x" * 180),
            "kind": "ci",
            "status": "completed",
            "conclusion": "success",
            "url": "https://example.test/" + ("x" * 700),
        }
        for index in range(100)
    ]
    assert report(oversized)["error"] == "input_exceeds_size_cap"

    deep: object = "leaf"
    for _ in range(1000):
        deep = [deep]
    deeply_nested = payload()
    deeply_nested["checks"] = deep
    nested_result = report(deeply_nested)
    assert nested_result["classification"] == "malformed"
    assert nested_result["error"] == "input_nesting_exceeds_limit"


def test_duplicate_json_keys_and_invalid_timestamps_fail_closed(tmp_path: Path):
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(
        '{"schema":"MarketOS.CIAdmissibilityEvidence.v1","schema":"MarketOS.CIAdmissibilityEvidence.v1"}',
        encoding="utf-8",
    )
    with pytest.raises(EvidenceInputError, match="duplicate_json_key"):
        load_input(duplicate, root=tmp_path)

    invalid = payload()
    invalid["workflow"]["created_at"] = "2026-99-99T99:99:99+00:00"
    result = report(invalid)
    assert result["classification"] == "malformed"
    assert result["error"] == "invalid_workflow_created_at"


def test_fingerprint_and_serialization_are_deterministic():
    first = report()
    second = report(copy.deepcopy(payload()))
    assert first == second
    assert first["fingerprint"] == second["fingerprint"]
    assert len(first["fingerprint"]) == 64
    assert render_json(first) == render_json(second)


def test_report_never_authorizes_merge_or_deployment():
    result = report()
    assert result["authority"] == {
        "kind": "evidence_classifier_only",
        "merge_authorized": False,
        "deployment_authorized": False,
        "external_actions_authorized": False,
        "integrated_consumers": [],
        "intended_consumers": ["scripts/ai/run_local_quality_gate.py", "scripts/ai/pr_readiness_report.py"],
    }


def test_bounded_renderers_preserve_valid_output():
    data = payload()
    data["jobs"] = []
    data["required_jobs"] = [f"job-{index}" for index in range(100)]
    data["required_policy"]["jobs"] = list(data["required_jobs"])
    data["required_policy"]["fingerprint"] = policy_digest(data["required_policy"])
    result = report(data)
    json_text = render_json(result)
    markdown = render_markdown(result)
    assert len(json_text) <= 120_000
    assert len(markdown) <= 120_000
    assert json.loads(json_text)["schema"] == REPORT_SCHEMA
    assert "Next action" in markdown

    large = report()
    large["jobs"] = [{"name": "job-" + ("x" * 1600), "classification": "pass"} for _ in range(100)]
    compact = json.loads(render_json(large))
    assert compact["output_bounded"] is True
    assert compact["classification"] == "pass"
    assert compact["status"] == "passed"
    assert compact["authority"]["merge_authorized"] is False
    assert compact["fingerprint"] == large["fingerprint"]


def test_sanitized_step_objects_are_accepted():
    data = payload()
    item = job(data)
    item.pop("steps_executed")
    item["steps"] = [{"name": "checkout", "status": "completed"}]
    result = report(data)
    assert result["classification"] == "pass"
    assert result["jobs"][0]["steps_executed"] == 1


def test_markdown_escapes_untrusted_job_names():
    data = payload()
    unsafe_name = "[link](javascript:alert(1))|`code`"
    data["required_jobs"] = [unsafe_name]
    data["required_policy"]["jobs"] = [unsafe_name]
    data["required_policy"]["fingerprint"] = policy_digest(data["required_policy"])
    data["jobs"][0]["name"] = unsafe_name
    markdown = render_markdown(report(data))
    assert "\\[link\\]" in markdown
    assert "[link](javascript:" not in markdown
    assert "\\|" in markdown


def test_input_size_and_path_safety_are_bounded(tmp_path: Path):
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + (b"x" * MAX_INPUT_BYTES) + b"}")
    with pytest.raises(EvidenceInputError, match="input_exceeds_size_cap"):
        load_input(oversized, root=tmp_path)
    outside = tmp_path.parent / "outside-ci-evidence.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(EvidenceInputError, match="input_outside_worktree"):
        load_input(outside, root=tmp_path)


def test_cli_json_and_markdown_are_offline_and_have_truthful_exit_codes(tmp_path: Path):
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(payload()), encoding="utf-8")
    command = [sys.executable, "scripts/ai/ci_admissibility_probe.py", "--input", str(valid), "--json", "--root", str(tmp_path)]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["classification"] == "pass"
    markdown = subprocess.run([sys.executable, "scripts/ai/ci_admissibility_probe.py", "--input", str(valid), "--markdown", "--root", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert markdown.returncode == 0
    assert "CI Admissibility Evidence" in markdown.stdout

    malformed = tmp_path / "malformed.json"
    malformed.write_text(json.dumps(fixture("malformed_raw_logs.json")), encoding="utf-8")
    bad = subprocess.run([sys.executable, "scripts/ai/ci_admissibility_probe.py", "--input", str(malformed), "--root", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert bad.returncode == 3
    assert json.loads(bad.stdout)["classification"] == "malformed"

    unavailable = tmp_path / "unavailable.json"
    blocked = payload()
    blocked["jobs"][0].update({"runner_id": 0, "runner_name": None, "steps_executed": 0, "log_status": "unavailable"})
    unavailable.write_text(json.dumps(blocked), encoding="utf-8")
    blocked_result = subprocess.run([sys.executable, "scripts/ai/ci_admissibility_probe.py", "--input", str(unavailable), "--root", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert blocked_result.returncode == 2
    assert json.loads(blocked_result.stdout)["classification"] == "ci_unavailable"

    failure = tmp_path / "failure.json"
    failed = payload()
    failed["workflow"]["conclusion"] = "failure"
    failed["jobs"][0].update({"conclusion": "failure", "required_check_status": "failure"})
    failure.write_text(json.dumps(failed), encoding="utf-8")
    failed_result = subprocess.run([sys.executable, "scripts/ai/ci_admissibility_probe.py", "--input", str(failure), "--root", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, check=False)
    assert failed_result.returncode == 1
    assert json.loads(failed_result.stdout)["classification"] == "executed_failure"
