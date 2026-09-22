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
