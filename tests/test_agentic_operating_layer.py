from __future__ import annotations

from scripts.ai import ci_matrix_plan, impact_planner, operating_layer, phase_gate, pr_readiness_report, select_tests


def test_impact_planner_ranks_by_score_deterministically():
    low = {"task": "low", "commercial": 1, "evidence": 1, "risk_reduction": 1, "unblocking": 1, "ci": 1, "operator": 1, "effort": 5, "scope_risk": 5, "safety_risk": 5, "gate": "none"}
    high = {**low, "task": "high", "commercial": 5, "evidence": 5, "risk_reduction": 5, "unblocking": 5, "effort": 1, "scope_risk": 1, "safety_risk": 1}
    report = impact_planner.plan([low, high])
    assert report["ranked_backlog"][0]["task"] == "high"
    assert report == impact_planner.plan([low, high])


def test_default_backlog_contains_current_cj_gate():
    assert impact_planner.plan(impact_planner.DEFAULT_BACKLOG)["ranked_backlog"]
    assert any(item["task"] == "run_cj_credentialed_readonly_validation" for item in impact_planner.DEFAULT_BACKLOG)
    assert any(item["task"] == "run_phase1_evidence_benchmark_matrix" for item in impact_planner.DEFAULT_BACKLOG)


def test_docs_only_selector_is_fast_and_safe():
    report = select_tests.select(["docs/ai/QUALITY_GATES.md", "README.md"])
    assert report["docs_only"] is True
    assert report["lanes"] == ["docs_only"]
    assert "git diff --check" in report["recommended_commands"]


def test_supplier_selector_includes_existing_evidence_regressions():
    report = select_tests.select(["backend/adapters/research/cj_readonly_api.py"])
    assert "supplier_evidence" in report["lanes"]
    assert any("test_cj_readonly_supplier" in command for command in report["recommended_commands"])


def test_evaluation_selector_includes_architecture_boundary():
    commands = select_tests.select(["evaluation/commerce/metrics.py"])["recommended_commands"]
    assert any("tests/evaluation" in command for command in commands)
    assert any("architecture_boundaries" in command for command in commands)


def test_api_selector_includes_read_view_regressions():
    commands = select_tests.select(["api/routes/canonical_events.py"])["recommended_commands"]
    assert any("canonical_events_api_readonly" in command for command in commands)


def test_frontend_selector_builds_without_adding_tests():
    assert select_tests.select(["frontend/src/pages/OperatorEventDashboard.tsx"])["recommended_commands"][0] == "cd frontend && npm run build"


def test_agent_script_selector_includes_session_finish():
    commands = select_tests.select(["scripts/ai/impact_planner.py"])["recommended_commands"]
    assert "python scripts/ai/session_finish.py --dry-run" in commands


def test_unknown_selector_has_conservative_fallback():
    report = select_tests.select(["core/unknown.py"])
    assert report["lanes"] == ["unknown_fallback"]
    assert any("compileall" in command for command in report["recommended_commands"])


def test_ci_matrix_docs_only_does_not_claim_workflow_change():
    report = ci_matrix_plan.plan(["docs/ai/PROMPT_QUEUE.md"])
    assert report["recommended_lanes"] == ["docs_only", "diff_check"]
    assert "does not alter GitHub Actions" in report["note"]


def test_phase_gate_blocks_encoded_candidate():
    report = phase_gate.check([], candidate="supplier_mutation")
    assert report["status"] == "blocked"
    assert report["blockers"] == ["supplier_mutation"]


def test_phase_gate_detects_artifacts_and_real_env_files():
    report = phase_gate.check(["artifacts/live.json", ".env"])
    assert set(report["blockers"]) == {"generated_artifacts", "credentials"}


def test_phase_gate_does_not_block_docs_that_describe_forbidden_actions():
    assert phase_gate.check(["docs/ai/QUALITY_GATES.md"], "create_order and ad spend are forbidden")["status"] == "clear"


def test_phase_gate_detects_supplier_mutation_text():
    assert "supplier_mutation" in phase_gate.check(["backend/supplier.py"], "create order through supplier")["blockers"]


def test_pr_readiness_blocks_artifacts():
    report = pr_readiness_report.report(["artifacts/result.json"], "", branch="codex/test")
    assert report["merge_readiness"] == "blocked"
    assert report["detections"]["artifacts_detected"] is True


def test_pr_readiness_blocks_secret_value_like_diff():
    report = pr_readiness_report.report(["backend/x.py"], '+CJ_API_KEY="very-secret-value"', branch="codex/test")
    assert report["detections"]["secret_value_like_detected"] is True
    assert report["risk_category"] == "blocked"


def test_pr_readiness_blocks_provider_mutation_terms():
    report = pr_readiness_report.report(["backend/x.py"], "client.create_order()", branch="codex/test")
    assert report["detections"]["provider_mutation_like_detected"] is True


def test_pr_readiness_docs_only_is_ready_for_review():
    report = pr_readiness_report.report(["docs/ai/QUALITY_GATES.md"], "client.create_order() is forbidden", branch="codex/test")
    assert report["merge_readiness"] == "ready_for_review"
    assert report["docs_touched"] is True


def test_pr_readiness_flags_unapproved_raw_payload_location():
    report = pr_readiness_report.report(["backend/provider_payload.py"], "", branch="codex/test")
    assert report["detections"]["raw_payload_risk"] is True


def test_markdown_renderer_is_stable_for_new_tool_reports():
    value = {"status": "clear", "commands": ["pytest -q"]}
    first = select_tests.render_json_or_markdown(value, markdown=True, title="Test")
    assert first == select_tests.render_json_or_markdown(value, markdown=True, title="Test")
    assert "# Test" in first


def test_pr_readiness_diff_reader_recovers_from_missing_stdout(monkeypatch):
    class Result:
        stdout = None
    monkeypatch.setattr(pr_readiness_report.subprocess, "run", lambda *args, **kwargs: Result())
    assert pr_readiness_report._diff_text(None) == ""


def test_pr_readiness_staged_mode_uses_cached_diff(monkeypatch):
    calls = []
    class Result:
        stdout = "safe"
    monkeypatch.setattr(pr_readiness_report.subprocess, "run", lambda command, **kwargs: calls.append(command) or Result())
    assert pr_readiness_report._diff_text(None, staged=True) == "safe"
    assert calls[0][-1] == "--cached"


def test_staged_paths_use_only_index_diff(monkeypatch):
    calls = []
    monkeypatch.setattr(operating_layer, "git_lines", lambda *args, **kwargs: calls.append(args) or ["evaluation/commerce/readiness.py"])
    assert operating_layer.staged_from_git() == ["evaluation/commerce/readiness.py"]
    assert calls[0] == ("diff", "--cached", "--name-only")


def test_pr_readiness_policy_labels_do_not_count_as_mutation_code():
    report = pr_readiness_report.report(["evaluation/commerce/readiness.py"], '+("supplier_mutation", "orders_payments_or_fulfillment")', branch="codex/test", mutation_diff="")
    assert report["detections"]["provider_mutation_like_detected"] is False


def _quality_gate_report(*, status="failed", classification="failure_origin_unverified", ci_status="passed", ci_classification="pass", delta_status="failed", delta_classification="mixed", controls=None, ready=False):
    return {
        "phase": "final",
        "status": status,
        "classification": classification,
        "ready_for_supervised_use": ready,
        "ci": {"status": ci_status, "classification": ci_classification},
        "checks": [
            {"name": "pytest", "status": "failed", "execution_status": "executed", "checks": []},
        ],
        "baseline_delta": {
            "status": delta_status,
            "classification": delta_classification,
            "classifications": sorted({delta_classification}),
            "baseline_available": delta_classification != "baseline_missing",
            "controls": controls or [],
            "fingerprint": "a" * 64,
        },
    }


def test_pr_readiness_separates_baseline_origins_and_executed_failures():
    quality_gate = _quality_gate_report(
        controls=[
            {"name": "pytest", "baseline_status": "passed", "candidate_status": "failed", "classification": "introduced_failure"},
            {"name": "ruff", "baseline_status": "failed", "candidate_status": "failed", "classification": "inherited_failure"},
            {"name": "typed", "baseline_status": "failed", "candidate_status": "passed", "classification": "resolved_failure"},
        ],
    )

    report = pr_readiness_report.report(["scripts/ai/run_local_quality_gate.py"], "", branch="codex/test", quality_gate=quality_gate)

    delta = report["quality_gate"]["baseline_delta"]
    assert delta["introduced_failures"] == ["pytest"]
    assert delta["inherited_failures"] == ["ruff"]
    assert delta["resolved_failures"] == ["typed"]
    assert delta["candidate_executed_failure"] == ["pytest"]
    assert report["quality_gate"]["blocking"] is True
    assert report["merge_readiness"] == "blocked"


def test_pr_readiness_preserves_ci_unavailable_and_incomplete_evidence():
    quality_gate = _quality_gate_report(
        status="unavailable",
        classification="ci_unavailable",
        ci_status="unavailable",
        ci_classification="ci_unavailable",
        delta_status="unavailable",
        delta_classification="candidate_incomplete",
        controls=[
            {"name": "ci", "baseline_status": "passed", "candidate_status": "unavailable", "classification": "candidate_incomplete"},
        ],
    )

    report = pr_readiness_report.report(["scripts/ai/run_local_quality_gate.py"], "", branch="codex/test", quality_gate=quality_gate)

    assert report["quality_gate"]["ci_classification"] == "ci_unavailable"
    assert report["quality_gate"]["baseline_delta"]["candidate_incomplete"] == ["ci"]
    assert "ci:ci_unavailable" in report["blocking_warnings"]
    assert report["merge_readiness"] == "blocked"
    assert report["quality_gate"]["ready_for_supervised_use"] is False


def test_pr_readiness_reports_missing_and_malformed_baselines_as_blockers():
    missing = _quality_gate_report(status="unavailable", classification="baseline_missing", delta_status="unavailable", delta_classification="baseline_missing")
    malformed = _quality_gate_report(status="configuration_error", classification="malformed", delta_status="malformed", delta_classification="malformed_baseline")

    missing_report = pr_readiness_report.report(["tests/test_local_quality_gate.py"], "", branch="codex/test", quality_gate=missing)
    malformed_report = pr_readiness_report.report(["tests/test_local_quality_gate.py"], "", branch="codex/test", quality_gate=malformed)

    assert missing_report["quality_gate"]["baseline_delta"]["classification"] == "baseline_missing"
    assert malformed_report["quality_gate"]["baseline_delta"]["classification"] == "malformed_baseline"
    assert missing_report["merge_readiness"] == "blocked"
    assert malformed_report["merge_readiness"] == "blocked"


def test_pr_readiness_projection_is_deterministic_and_legacy_invocation_is_unchanged():
    quality_gate = _quality_gate_report(
        status="passed",
        classification="pass",
        delta_status="passed",
        delta_classification="resolved_failure",
        controls=[{"name": "pytest", "baseline_status": "failed", "candidate_status": "passed", "classification": "resolved_failure"}],
        ready=True,
    )
    first = pr_readiness_report.report(["docs/ai/QUALITY_GATES.md"], "", branch="codex/test", quality_gate=quality_gate)
    second = pr_readiness_report.report(["docs/ai/QUALITY_GATES.md"], "", branch="codex/test", quality_gate=quality_gate)
    legacy = pr_readiness_report.report(["docs/ai/QUALITY_GATES.md"], "", branch="codex/test")

    assert first == second
    assert first["quality_gate"]["baseline_delta"]["resolved_failures"] == ["pytest"]
    assert legacy["quality_gate"] == {"provided": False}
    assert legacy["merge_readiness"] == "ready_for_review"
