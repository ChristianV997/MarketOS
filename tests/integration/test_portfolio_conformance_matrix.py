from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ai.portfolio_conformance_matrix import (
    INPUT_SCHEMA,
    MAX_INPUT_BYTES,
    SCHEMA,
    MatrixInputError,
    build_matrix,
    load_input,
    normalize_input,
    render_markdown,
    render_json,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "portfolio_conformance"
MAIN = "df160af1aad615dcdee7934bcd7122898eb5eff1"
REPO_STATE = {
    "classification": "actual",
    "head": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "branch": "codex/portfolio-conformance-matrix-c1",
    "origin_main": MAIN,
    "merge_base": MAIN,
    "field_classifications": {"head": "actual", "branch": "actual", "origin_main": "actual", "merge_base": "actual"},
}


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def matrix() -> dict:
    return build_matrix(fixture("mixed_portfolio.json"), repository_state=REPO_STATE)


def by_number(report: dict, number: int) -> dict:
    return next(item for item in report["pull_requests"] if item["number"] == number)


def test_schema_and_repository_identity_are_explicit():
    report = matrix()
    assert report["schema"] == SCHEMA
    assert report["repository"] == "ChristianV997/MarketOS"
    assert report["origin_main"] == MAIN
    assert report["repository_state"]["classification"] == "actual"
    assert report["merge_authority"] == "scripts/ai/pr_readiness_report.py"
    assert report["merge_authorized"] is False


def test_changed_file_collision_and_duplicate_authority_are_visible():
    report = matrix()
    assert {item["path"] for item in report["overlap"]["collisions"]} == {
        "backend/service_delivery/workbench.py",
        "scripts/ai/pr_readiness_report.py",
    }
    kinds = {item["kind"] for item in report["duplicate_authority_indicators"]}
    assert "changed_file_overlap" in kinds
    assert "canonical_authority_overlap" in kinds
    assert "parallel_authority_claim" in kinds
    assert "overlap:scripts/ai/pr_readiness_report.py" in by_number(report, 299)["blockers"]


def test_executed_failure_is_not_ci_unavailable():
    pr = by_number(matrix(), 275)
    assert pr["ci"]["classification"] == "executed_failure"
    assert pr["ci"]["jobs"][0]["steps_executed"] == 3
    assert pr["ci"]["jobs"][0]["runner_assigned"] is True
    assert "ci:executed_failure" in pr["blockers"]


def test_zero_step_runnerless_failure_is_ci_unavailable_not_failure():
    pr = by_number(matrix(), 279)
    assert pr["ci"]["classification"] == "ci_unavailable"
    assert all(job["classification"] == "zero_step_runnerless" for job in pr["ci"]["jobs"])
    assert "ci:ci_unavailable" in pr["blockers"]
    assert "ci:executed_failure" not in pr["blockers"]


def test_missing_logs_do_not_turn_success_into_pass():
    pr = by_number(matrix(), 299)
    assert pr["ci"]["classification"] == "unavailable_logs"
    assert pr["ci"]["jobs"][0]["classification"] == "unavailable_logs"
    assert "ci:unavailable_logs" in pr["blockers"]


def test_pending_required_check_is_not_passed():
    pr = by_number(matrix(), 285)
    assert pr["ci"]["classification"] == "pending"
    assert pr["ci"]["jobs"][0]["classification"] == "pending"
    assert pr["local_evidence"]["classification"] == "not_run"
    assert "ci:pending" in pr["blockers"]


def test_pass_requires_runner_steps_and_logs():
    pr = by_number(matrix(), 271)
    assert pr["ci"]["classification"] == "pass"
    assert pr["ci"]["jobs"][0]["classification"] == "pass"
    assert by_number(matrix(), 300)["ci"]["classification"] == "pass"


def test_merged_dependency_and_stacked_ancestry_are_distinguished():
    merged = by_number(matrix(), 275)
    stacked = by_number(matrix(), 300)
    assert merged["stacking"]["dependencies"] == [{"number": 271, "classification": "merged_dependency_satisfied"}]
    assert stacked["ancestry"]["classification"] == "stacked_aligned"
    assert stacked["stacking"]["classification"] == "clear"
    assert report_order(matrix()) == [275, 279, 281, 285, 299, 300]


def report_order(report: dict) -> list[int]:
    return report["merge_order"]


def test_local_fixture_and_simulated_evidence_never_becomes_live():
    report = matrix()
    assert by_number(report, 279)["local_evidence"]["live_validated"] is False
    assert by_number(report, 299)["local_evidence"]["live_validated"] is False
    assert by_number(report, 281)["local_evidence"]["live_validated"] is False
    assert by_number(report, 271)["local_evidence"]["execution_observed"] is True
    assert by_number(report, 271)["local_evidence"]["live_validated"] is False
    assert report["evidence_classifications"]["local"] == {
        "actual_executed": 3,
        "fixture": 1,
        "manual": 1,
        "not_run": 1,
        "simulated_or_planned": 1,
    }


def test_local_executed_failure_is_a_blocker_even_when_ci_is_not_the_failure():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["local_evidence"] = {"classification": "actual_executed", "status": "failed"}
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert "local_evidence_status:failed" in by_number(report, 271)["blockers"]


def test_report_keeps_current_git_origin_separate_from_adapter_origin():
    report = build_matrix(fixture("mixed_portfolio.json"), repository_state={**REPO_STATE, "origin_main": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
    assert report["origin_main"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert report["input_origin_main"] == MAIN
    assert "origin_main_mismatch" in report["blockers"]


def test_global_blockers_and_next_action_are_deterministic():
    first = matrix()
    second = matrix()
    assert first == second
    assert first["portfolio_status"] == "blocked"
    assert first["merge_authorized"] is False
    assert first["next_action"] == "resolve changed-file and canonical-authority ownership overlaps before merging"
    assert first["fingerprint"] == second["fingerprint"]
    assert len(first["fingerprint"]) == 64


def test_missing_dependency_head_blocks_and_does_not_guess_order():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 300)
    target["depends_on"] = [{"number": 998, "head_sha": "8888888888888888888888888888888888888888", "available": False}]
    target["base_ref"] = "missing-base"
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 300)
    assert pr["stacking"]["classification"] == "blocked"
    assert "missing_dependency_head:998" in pr["blockers"]
    assert any(item.startswith("pr:300:missing_dependency_head") for item in report["blockers"])


def test_stale_dependency_head_is_distinct_from_missing_dependency_head():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 300)
    target["depends_on"][0]["head_sha"] = "8888888888888888888888888888888888888888"
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 300)
    assert pr["stacking"]["dependencies"] == [{"number": 275, "classification": "stale_dependency_head"}]
    assert "stale_dependency_head:275" in pr["blockers"]


def test_stale_base_and_merge_base_are_blockers():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["base_sha"] = "9999999999999999999999999999999999999999"
    target["merge_base_sha"] = "8888888888888888888888888888888888888888"
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert by_number(report, 271)["ancestry"]["classification"] == "stale"
    assert "pr:271:ancestry:stale" in report["blockers"]


def test_malformed_raw_log_input_fails_closed_without_echoing_content():
    payload = fixture("malformed_raw_logs.json")
    report = build_matrix(payload, repository_state=REPO_STATE)
    rendered = json.dumps(report, sort_keys=True)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["classification"] == "malformed"
    assert "portfolio_input_malformed" in report["blockers"]
    assert "raw log content" not in rendered


def test_unknown_field_fails_closed():
    payload = fixture("mixed_portfolio.json")
    payload["pull_requests"][0]["private_notes"] = "do not echo"
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "unknown_or_forbidden_input_field"


def test_secret_like_title_is_rejected_without_leaking_value():
    payload = fixture("mixed_portfolio.json")
    secret = "ghp_" + ("x" * 32)
    payload["pull_requests"][0]["title"] = secret
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert secret not in json.dumps(report)


def test_required_check_missing_is_ci_unavailable():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["required_checks"] = ["test", "semgrep"]
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "ci_unavailable"
    assert pr["ci"]["missing_required"] == ["semgrep"]


def test_required_flag_mismatch_is_malformed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0]["required"] = False
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "ci_required_flag_mismatch"


def test_duplicate_jobs_are_malformed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"].append(dict(target["ci_jobs"][0]))
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "duplicate_ci_job"


def test_timeout_is_preserved_as_timeout():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0]["conclusion"] = "timed_out"
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert by_number(report, 271)["ci"]["classification"] == "timed_out"


def test_ci_head_binding_and_contradictory_pending_metadata_fail_closed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0]["head_sha"] = "9999999999999999999999999999999999999999"
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "ci_head_sha_mismatch"

    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 285)
    target["ci_jobs"][0]["conclusion"] = "success"
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "contradictory_pending_ci_metadata"


def test_actual_execution_is_not_live_commercial_validation():
    payload = fixture("mixed_portfolio.json")
    report = build_matrix(payload, repository_state=REPO_STATE)
    evidence = by_number(report, 300)["local_evidence"]
    assert evidence["execution_observed"] is True
    assert evidence["live_validated"] is False


def test_repository_identity_mismatch_blocks_without_echoing_remote_url():
    report = build_matrix(
        fixture("mixed_portfolio.json"),
        repository_state={**REPO_STATE, "remote_repository": "OtherOrg/OtherRepo"},
    )
    assert report["portfolio_status"] == "blocked"
    assert "repository_mismatch" in report["blockers"]


def test_input_normalization_is_sorted_and_schema_checked():
    payload = fixture("mixed_portfolio.json")
    payload["pull_requests"] = list(reversed(payload["pull_requests"]))
    normalized = normalize_input(payload)
    assert [item["number"] for item in normalized["pull_requests"]] == sorted(item["number"] for item in normalized["pull_requests"])
    assert normalized["schema"] == INPUT_SCHEMA
    with pytest.raises(MatrixInputError, match="unsupported_input_schema"):
        normalize_input({**payload, "schema": "other"})


def test_load_input_enforces_size_cap(tmp_path: Path):
    path = tmp_path / "oversized.json"
    path.write_bytes(b"{" + b"x" * MAX_INPUT_BYTES + b"}")
    with pytest.raises(MatrixInputError, match="input_exceeds_size_cap"):
        load_input(path)


def test_sensitive_input_path_is_rejected(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(MatrixInputError, match="sensitive_input_path"):
        from scripts.ai.portfolio_conformance_matrix import _safe_input_path

        _safe_input_path(path, root=tmp_path)


def test_markdown_is_bounded_and_contains_operator_action():
    rendered = render_markdown(matrix())
    assert len(rendered) < 120_000
    assert "# MarketOS Portfolio Conformance Matrix" in rendered
    assert "Proposed Order" in rendered
    assert "Next action" in rendered
    assert "ci_unavailable" in rendered
    assert "raw log content" not in rendered


def test_json_renderer_preserves_valid_bounded_output():
    payload = fixture("mixed_portfolio.json")
    for number in range(301, 344):
        payload["pull_requests"].append(
            {
                "number": number,
                "title": f"bounded {number}",
                "state": "open",
                "is_draft": True,
                "base_ref": "main",
                "base_sha": MAIN,
                "head_ref": f"bounded-{number}",
                "head_sha": f"{number:040x}",
                "merge_base_sha": MAIN,
                "changed_files": [f"docs/ai/bounded-{number}-{index}.md" for index in range(250)],
                "depends_on": [],
                "required_checks": ["test"],
                    "required_checks_source": "branch_protection_adapter",
                    "ci_jobs": [{"name": "test", "status": "completed", "conclusion": "success", "required": True, "head_sha": f"{number:040x}", "runner_id": number, "steps_executed": 1, "logs_available": True}],
                "local_evidence": {"classification": "actual_executed", "status": "passed"},
            }
        )
    report = build_matrix(payload, repository_state=REPO_STATE)
    rendered = render_json(report)
    parsed = json.loads(rendered)
    assert len(rendered) <= 120_000
    assert parsed["output_bounded"] is True
    assert parsed["merge_authorized"] is False


def test_origin_main_mismatch_blocks_even_when_pr_rows_are_valid():
    report = build_matrix(fixture("mixed_portfolio.json"), repository_state={**REPO_STATE, "origin_main": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
    assert "origin_main_mismatch" in report["blockers"]
    assert report["portfolio_status"] == "blocked"


def test_no_input_is_useful_but_not_a_green_portfolio():
    report = build_matrix(None, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "blocked"
    assert report["blockers"] == ["portfolio_input_not_supplied"]
    assert report["merge_authorized"] is False


def test_non_ci_marker_in_required_checks_fails_closed():
    payload = fixture("mixed_portfolio.json")
    payload["pull_requests"][0]["required_checks"] = ["netlify/deploy-preview"]
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "non_ci_check_in_required_checks"


def test_deploy_preview_job_separated_from_ci_and_cannot_satisfy_ci_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["required_checks"] = ["test"]
    # Netlify job declared with required=True must fail closed
    target["ci_jobs"].append(
        {
            "name": "netlify/marketos/deploy-preview",
            "status": "completed",
            "conclusion": "success",
            "required": True,
            "head_sha": target["head_sha"],
            "runner_id": 199,
            "steps_executed": 2,
            "logs_available": True,
        }
    )
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "non_ci_job_cannot_be_required"

    # When not required, it must be segregated to non_ci_checks and not satisfy CI
    target["ci_jobs"][-1]["required"] = False
    report_valid = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report_valid, 271)
    assert pr["ci"]["classification"] == "pass"
    assert len(pr["ci"]["non_ci_checks"]) == 1
    assert pr["ci"]["non_ci_checks"][0]["kind"] == "deploy_preview"
    assert pr["ci"]["non_ci_checks"][0]["name"] == "netlify/marketos/deploy-preview"


def test_explicit_workflow_name_and_job_identity_preserved():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0]["workflow_name"] = "Agentic Quality Gate"
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["jobs"][0]["workflow_name"] == "Agentic Quality Gate"


def test_contradictory_in_progress_with_logs_available_fails_closed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0].update({"status": "in_progress", "conclusion": None, "logs_available": True, "runner_id": 101})
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "contradictory_in_progress_ci_metadata"


def test_cross_client_and_cross_workspace_portfolio_rows_fail_closed():
    payload = fixture("mixed_portfolio.json")
    payload["pull_requests"][0]["client_id"] = "client-alpha"
    payload["pull_requests"][1]["client_id"] = "client-beta"
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "cross_client_portfolio_rows"

    # Mismatched workspaces also fail closed
    payload2 = fixture("mixed_portfolio.json")
    payload2["pull_requests"][0]["workspace_id"] = "ws-one"
    payload2["pull_requests"][1]["workspace_id"] = "ws-two"
    report2 = build_matrix(payload2, repository_state=REPO_STATE)
    assert report2["portfolio_status"] == "malformed"
    assert report2["input"]["error"] == "cross_workspace_portfolio_rows"

    # Consistent workspace and candidate identities are retained
    payload3 = fixture("mixed_portfolio.json")
    payload3["workspace_id"] = "ws-canonical"
    payload3["client_id"] = "client-canonical"
    for item in payload3["pull_requests"]:
        item["workspace_id"] = "ws-canonical"
        item["client_id"] = "client-canonical"
        item["candidate_id"] = f"candidate-{item['number']}"
    report3 = build_matrix(payload3, repository_state=REPO_STATE)
    assert report3["workspace_id"] == "ws-canonical"
    assert report3["client_id"] == "client-canonical"
    pr3 = by_number(report3, 271)
    assert pr3["workspace_id"] == "ws-canonical"
    assert pr3["client_id"] == "client-canonical"
    assert pr3["candidate_id"] == "candidate-271"


def test_missing_versus_explicit_zero_economics():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["economics"] = {"gross_margin": 0.0, "currency": "USD", "evidence_state": "simulated"}
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["economics"]["classification"] == "explicit_zero"
    assert pr["economics"]["gross_margin"] == "0.0"

    # PR without economics remains None/missing, not laundered into 0.0
    pr_no_econ = by_number(report, 275)
    assert pr_no_econ["economics"] is None


def test_failed_step_in_step_list_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0].pop("steps_executed", None)
    target["ci_jobs"][0]["steps"] = [
        {"name": "checkout", "status": "completed"},
        {"name": "test-execution", "status": "failure"},
    ]
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "ci_unavailable"
    assert pr["ci"]["status"] == "unavailable"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["jobs"][0]["classification"] == "incomplete_steps"
    assert pr["ci"]["jobs"][0]["step_outcome"] == "incomplete"
    assert "ci:ci_unavailable" in pr["blockers"]


def test_skipped_step_in_step_list_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0].pop("steps_executed", None)
    target["ci_jobs"][0]["steps"] = [
        {"name": "checkout", "status": "completed"},
        {"name": "test-execution", "status": "skipped"},
    ]
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "ci_unavailable"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["jobs"][0]["classification"] == "incomplete_steps"
    assert pr["ci"]["jobs"][0]["step_outcome"] == "incomplete"
    assert "ci:ci_unavailable" in pr["blockers"]


def test_pending_step_in_step_list_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0].pop("steps_executed", None)
    target["ci_jobs"][0]["steps"] = [
        {"name": "checkout", "status": "completed"},
        {"name": "test-execution", "status": "pending"},
    ]
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "pending"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["jobs"][0]["classification"] == "pending"
    assert pr["ci"]["jobs"][0]["step_outcome"] == "pending"
    assert "ci:pending" in pr["blockers"]


def test_required_check_status_failure_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0]["required_check_status"] = "failure"
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "executed_failure"
    assert pr["ci"]["status"] == "failed"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["jobs"][0]["classification"] == "executed_failure"
    assert "ci:executed_failure" in pr["blockers"]


def test_required_check_status_pending_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_jobs"][0].update({"status": "in_progress", "conclusion": None, "required_check_status": "pending", "logs_available": False})
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "pending"
    assert pr["ci"]["status"] == "pending"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["jobs"][0]["classification"] == "pending"
    assert "ci:pending" in pr["blockers"]


def test_workflow_conclusion_failure_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["workflow"] = {"name": "Agentic Quality Gate", "status": "completed", "conclusion": "failure"}
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "executed_failure"
    assert pr["ci"]["status"] == "failed"
    assert pr["ci"]["admissible_evidence"] is False
    assert "ci:executed_failure" in pr["blockers"]


def test_workflow_conclusion_pending_cannot_be_flattened_into_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["workflow_conclusion"] = "pending"
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "pending"
    assert pr["ci"]["status"] == "pending"
    assert pr["ci"]["admissible_evidence"] is False
    assert "ci:pending" in pr["blockers"]


def test_ci_report_with_contradictory_diagnostic_state_fails_closed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "unavailable",
        "classification": "ci_unavailable",
        "diagnostic_state": "pass",  # Contradicts classification != pass
        "diagnostic_states": ["pass"],
        "admissible_evidence": False,
        "candidate_head_sha": target["head_sha"],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "contradictory_ci_diagnostic_metadata"


def test_ci_report_with_contradictory_admissible_evidence_fails_closed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "failed",
        "classification": "executed_failure",
        "diagnostic_state": "executed_failure",
        "diagnostic_states": ["executed_failure"],
        "admissible_evidence": True,  # Contradicts classification != pass
        "candidate_head_sha": target["head_sha"],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "contradictory_ci_diagnostic_metadata"


def test_ci_report_consumption_preserves_ci_unavailable_and_blocks():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "unavailable",
        "classification": "ci_unavailable",
        "diagnostic_state": "zero_step_runnerless",
        "diagnostic_states": ["zero_step_runnerless"],
        "admissible_evidence": False,
        "candidate_head_sha": target["head_sha"],
        "required_jobs": ["test"],
        "missing_required_jobs": [],
        "jobs": [
            {
                "name": "test",
                "classification": "zero_step_runnerless",
                "status": "unavailable",
                "required": True,
            }
        ],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "ci_unavailable"
    assert pr["ci"]["status"] == "unavailable"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["diagnostic_state"] == "zero_step_runnerless"
    assert "ci:ci_unavailable" in pr["blockers"]


def test_non_ci_marker_evasion_with_dots_or_unicode_is_detected():
    payload = fixture("mixed_portfolio.json")
    payload["pull_requests"][0]["required_checks"] = ["netlify.deploy.preview"]
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "non_ci_check_in_required_checks"

    # In ci_jobs, dots are recognized as non-ci and segregated
    payload2 = fixture("mixed_portfolio.json")
    target2 = next(item for item in payload2["pull_requests"] if item["number"] == 271)
    target2["ci_jobs"].append(
        {
            "name": "netlify.marketos.deploy.preview",
            "status": "completed",
            "conclusion": "success",
            "required": False,
            "head_sha": target2["head_sha"],
            "runner_id": 199,
            "steps_executed": 2,
            "logs_available": True,
        }
    )
    report2 = build_matrix(payload2, repository_state=REPO_STATE)
    pr2 = by_number(report2, 271)
    assert pr2["ci"]["classification"] == "pass"
    assert any(c["name"] == "netlify.marketos.deploy.preview" for c in pr2["ci"]["non_ci_checks"])


def test_diagnostic_fields_never_report_pass_when_ci_is_not_pass():
    report = matrix()
    for pr in report["pull_requests"]:
        ci = pr["ci"]
        if ci["classification"] != "pass":
            assert ci["diagnostic_state"] != "pass", f"PR #{pr['number']} had diagnostic_state 'pass' but classification '{ci['classification']}'"
            assert "pass" not in ci["diagnostic_states"]
            assert ci["admissible_evidence"] is False
            assert ci["status"] != "passed"
        else:
            assert ci["diagnostic_state"] == "pass"
            assert ci["admissible_evidence"] is True
            assert ci["status"] == "passed"


def test_ci_report_target_head_and_base_mismatch_fail_closed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "passed",
        "classification": "pass",
        "diagnostic_state": "pass",
        "diagnostic_states": ["pass"],
        "admissible_evidence": True,
        "candidate_head_sha": target["head_sha"],
        "target_head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "required_jobs": ["test"],
        "missing_required_jobs": [],
        "jobs": [],
        "non_ci_checks": [],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "ci_report_head_sha_mismatch"

    # Mismatched target_base_sha also fails closed
    target["ci_report"]["target_head_sha"] = target["head_sha"]
    target["ci_report"]["target_base_sha"] = "cccccccccccccccccccccccccccccccccccccccc"
    report2 = build_matrix(payload, repository_state=REPO_STATE)
    assert report2["portfolio_status"] == "malformed"
    assert report2["input"]["error"] == "ci_report_base_sha_mismatch"


def test_ci_report_contradictory_workflow_conclusion_fails_closed():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "passed",
        "classification": "pass",
        "diagnostic_state": "pass",
        "diagnostic_states": ["pass"],
        "admissible_evidence": True,
        "candidate_head_sha": target["head_sha"],
        "workflow": {"conclusion": "failure"},
        "required_jobs": ["test"],
        "missing_required_jobs": [],
        "jobs": [],
        "non_ci_checks": [],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    assert report["portfolio_status"] == "malformed"
    assert report["input"]["error"] == "contradictory_ci_diagnostic_metadata"


def test_ci_report_missing_consumer_required_check_cannot_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["required_checks"] = ["test", "lint"]
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "passed",
        "classification": "pass",
        "diagnostic_state": "pass",
        "diagnostic_states": ["pass"],
        "admissible_evidence": True,
        "candidate_head_sha": target["head_sha"],
        "required_jobs": ["test"],
        "missing_required_jobs": [],
        "jobs": [],
        "non_ci_checks": [],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "ci_unavailable"
    assert pr["ci"]["status"] == "unavailable"
    assert pr["ci"]["admissible_evidence"] is False
    assert pr["ci"]["missing_required"] == ["lint"]
    assert "ci:ci_unavailable" in pr["blockers"]
    assert "lint" in pr["blockers"]


def test_ci_report_top_level_workflow_failure_cannot_pass():
    payload = fixture("mixed_portfolio.json")
    target = next(item for item in payload["pull_requests"] if item["number"] == 271)
    target["workflow_conclusion"] = "failure"
    target["ci_report"] = {
        "schema": "MarketOS.CIAdmissibilityReport.v1",
        "status": "passed",
        "classification": "pass",
        "diagnostic_state": "pass",
        "diagnostic_states": ["pass"],
        "admissible_evidence": True,
        "candidate_head_sha": target["head_sha"],
        "required_jobs": ["test"],
        "missing_required_jobs": [],
        "jobs": [],
        "non_ci_checks": [],
    }
    report = build_matrix(payload, repository_state=REPO_STATE)
    pr = by_number(report, 271)
    assert pr["ci"]["classification"] == "executed_failure"
    assert pr["ci"]["status"] == "failed"
    assert pr["ci"]["admissible_evidence"] is False
    assert "ci:executed_failure" in pr["blockers"]


def test_producer_consumer_boundary_matrix_covers_all_catalog_states():
    catalog_cases = [
        ("zero_step_runnerless", "ci_unavailable", "unavailable", False, "zero_step_runnerless"),
        ("executed_failure_logs", "executed_failure", "failed", False, "executed_failure"),
        ("executed_timeout", "timed_out", "timed_out", False, "timed_out"),
        ("executed_success", "pass", "passed", True, "pass"),
        ("success_missing_logs", "ci_unavailable", "unavailable", False, "unavailable_logs"),
        ("failure_logs_404", "executed_failure", "failed", False, "executed_failure"),
        ("pending_job", "pending", "pending", False, "pending"),
        ("stale_job_metadata", "ci_unavailable", "unavailable", False, "stale_job_metadata"),
        ("missing_workflow_context", "ci_unavailable", "unavailable", False, "missing_workflow_context"),
    ]
    for case_name, exp_class, exp_status, exp_admissible, exp_diag in catalog_cases:
        payload = fixture("mixed_portfolio.json")
        target = next(item for item in payload["pull_requests"] if item["number"] == 271)
        target["ci_report"] = {
            "schema": "MarketOS.CIAdmissibilityReport.v1",
            "status": exp_status,
            "classification": exp_class,
            "diagnostic_state": exp_diag,
            "diagnostic_states": [exp_diag],
            "admissible_evidence": exp_admissible,
            "candidate_head_sha": target["head_sha"],
            "target_head_sha": target["head_sha"],
            "target_base_sha": target["base_sha"],
            "required_jobs": ["test"],
            "missing_required_jobs": [],
            "jobs": [{"name": "test", "classification": exp_diag, "status": exp_status, "required": True}],
            "non_ci_checks": [],
        }
        report = build_matrix(payload, repository_state=REPO_STATE)
        pr = by_number(report, 271)
        assert pr["ci"]["classification"] == exp_class, f"Failed on {case_name}"
        assert pr["ci"]["status"] == exp_status, f"Failed on {case_name}"
        assert pr["ci"]["admissible_evidence"] is exp_admissible, f"Failed on {case_name}"
        if not exp_admissible:
            assert f"ci:{exp_class}" in pr["blockers"], f"Missing blocker on {case_name}"
        assert report["merge_authorized"] is False
