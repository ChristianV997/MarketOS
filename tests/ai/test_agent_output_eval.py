from __future__ import annotations

from scripts.ai.agent_output_eval import SCHEMA, evaluate_report
from scripts.ai.operator_task_packet import validate_packet


def _packet():
    return validate_packet(
        {
            "agent_id": "grok-ai-development-tooling-engineer",
            "source_chat": "Grok Chat",
            "lane": "AI-CHAT-DEVELOPER-TOOLING-RETROFIT-V1",
            "objective": "Evaluate agent reports",
            "allowed_scope": ["scripts/ai/agent_output_eval.py", "tests/ai/test_agent_output_eval.py"],
            "prohibited_scope": ["artifacts/"],
            "base_sha": "df59a0609897907c1565d7d5f78e20959095d430",
            "worktree": "MarketOS.worktrees/ai-chat-tooling",
            "dependencies": ["MarketOS.AITask.v1"],
            "acceptance_criteria": ["eval fails closed"],
            "selected_tests": ["python -m pytest -q tests/ai/test_agent_output_eval.py"],
            "evidence_classification": "actual",
            "rollback": "delete branch",
            "next_action": "review findings",
        }
    )


def test_schema_constant():
    assert SCHEMA == "MarketOS.AgentEval.v1"


def test_passing_report():
    report = {
        "claims": ["focused tests passed"],
        "executed_commands": ["python -m pytest -q tests/ai/test_agent_output_eval.py"],
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "pr": 254,
        "rollback": "delete branch",
        "evidence_classification": "actual",
        "check_classifications": {"ruff": "not_run"},
        "status": "incomplete",
    }
    document, code = evaluate_report(report, _packet())
    assert code == 0
    assert document["overall"] == "passed"


def test_unavailable_must_not_become_passed():
    report = {
        "claims": ["quality gate passed"],
        "executed_commands": ["echo skip"],
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "pr": 1,
        "rollback": "revert",
        "check_classifications": {"github_ci": "unavailable"},
        "status": "passed",
    }
    document, code = evaluate_report(report, _packet())
    assert code == 2
    assert any(item["rule"] == "unavailable_not_passed" for item in document["findings"])


def test_fixture_must_not_become_live():
    report = {
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "pr": 1,
        "rollback": "revert",
        "evidence_classification": "fixture",
        "live_label": "live_validated",
    }
    document, code = evaluate_report(report, _packet())
    assert code == 2
    assert any(item["rule"] == "fixture_not_live" for item in document["findings"])


def test_scope_and_pr_and_rollback():
    report = {
        "changed_files": ["backend/economics/kernel.py"],
        "claims": ["done"],
    }
    document, code = evaluate_report(report, _packet())
    assert code == 2
    rules = {item["rule"] for item in document["findings"]}
    assert "changed_files_match_scope" in rules
    assert "pr_must_exist" in rules
    assert "rollback_must_exist" in rules


def test_packet_rollback_does_not_excuse_missing_report_rollback():
    report = {
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "pr": 1,
        "evidence_classification": "actual",
    }
    document, code = evaluate_report(report, _packet())
    assert code == 2
    assert any(item["rule"] == "rollback_must_exist" for item in document["findings"])


def test_undeclared_owned_files():
    report = {
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "owned_files": ["scripts/ai/agent_output_eval.py", "docs/secret-plan.md"],
        "pr": 1,
        "rollback": "revert",
    }
    document, code = evaluate_report(report, _packet())
    assert code == 2
    assert any(item["rule"] == "undeclared_files" for item in document["findings"])


def test_duplicate_authority_and_secrets_and_full_suite():
    report = {
        "claims": ["full suite passed"],
        "executed_commands": ["python -m pytest -q tests/ai/test_agent_output_eval.py"],
        "changed_files": ["scripts/ai/run_local_quality_gate.py"],
        "owned_files": ["scripts/ai/run_local_quality_gate.py"],
        "pr": 1,
        "rollback": "revert",
        "token": "ghp_abcdefghijklmnopqrstuvwxyz1234",
    }
    document, code = evaluate_report(report, _packet())
    assert code == 2
    rules = {item["rule"] for item in document["findings"]}
    assert "duplicate_authority_rejected" in rules
    assert "raw_secrets" in rules
    assert "full_suite_requires_command" in rules


def test_deterministic_output_order():
    report = {
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "pr": 9,
        "rollback": "revert",
    }
    first, _ = evaluate_report(report, _packet())
    second, _ = evaluate_report(report, _packet())
    assert first == second
    assert [item["rule"] for item in first["checks"]] == [item["rule"] for item in second["checks"]]
