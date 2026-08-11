from __future__ import annotations

from scripts.ai import run_local_quality_gate as gate


def test_no_changes_is_clear_and_offline():
    report = gate.run([])
    assert report["status"] == "clear"
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["phase1_readiness"]["next_best_action"]
    assert report["benchmark_matrix"]["evidence_mode"] == "fixture_demo"
    assert report["impact_top_task"] == "run_cj_credentialed_readonly_validation"


def test_docs_only_is_advisory_with_docs_lane():
    report = gate.run(["docs/ai/QUALITY_GATES.md"])
    assert report["status"] == "advisory"
    assert report["recommended_ci_lanes"] == ["docs_only", "diff_check"]
    assert report["recommended_tests"] == ["git diff --check", "python scripts/ai/session_finish.py --dry-run"]


def test_supplier_adapter_selects_supplier_regressions():
    report = gate.run(["backend/adapters/research/cj_readonly_api.py"])
    assert any("test_cj_readonly_supplier" in command for command in report["recommended_tests"])
    assert "supplier_evidence" in report["recommended_ci_lanes"]


def test_evaluation_and_frontend_files_choose_their_specific_lanes():
    evaluation = gate.run(["evaluation/commerce/metrics.py"])
    frontend = gate.run(["frontend/src/pages/OperatorEventDashboard.tsx"])
    assert "evaluation" in evaluation["recommended_ci_lanes"]
    assert "frontend" in frontend["recommended_ci_lanes"]


def test_env_file_blocks_without_exposing_content():
    report = gate.run([".env"], diff_text="CJ_API_KEY=long-secret-value")
    assert report["status"] == "blocked"
    assert report["secret_or_artifact_flags"]["credential_file_detected"] is True
    assert report["secret_or_artifact_flags"]["secret_value_like_detected"] is True


def test_artifact_file_blocks():
    report = gate.run(["artifacts/live/report.json"])
    assert report["status"] == "blocked"
    assert report["secret_or_artifact_flags"]["artifacts_detected"] is True


def test_mutation_like_diff_blocks_phase_gate():
    report = gate.run(["backend/adapter.py"], diff_text="client.create_order()")
    assert report["status"] == "blocked"
    assert report["mutation_flags"]["provider_mutation_like_detected"] is True
    assert "supplier_mutation" in report["phase_gate_blockers"]


def test_unknown_file_has_safe_fallback():
    report = gate.run(["core/new_module.py"])
    assert "unknown_fallback" in report["recommended_ci_lanes"]
    assert report["status"] == "advisory"


def test_result_is_deterministic_for_explicit_inputs():
    first = gate.run(["scripts/ai/select_tests.py"], diff_text="", branch="codex/example")
    assert first == gate.run(["scripts/ai/select_tests.py"], diff_text="", branch="codex/example")


def test_doc_mutation_language_does_not_block_a_mixed_implementation_diff():
    diff = """diff --git a/docs/guide.md b/docs/guide.md
+create_order is forbidden
diff --git a/scripts/ai/tool.py b/scripts/ai/tool.py
+print('safe')
"""
    report = gate.run(["docs/guide.md", "scripts/ai/tool.py"], diff_text=diff)
    assert report["status"] == "advisory"
    assert report["mutation_flags"]["provider_mutation_like_detected"] is False


def test_diff_reader_recovers_when_subprocess_returns_no_stdout(monkeypatch):
    class Result:
        stdout = None
    monkeypatch.setattr(gate.subprocess, "run", lambda *args, **kwargs: Result())
    assert gate._diff_text(None) == ""
