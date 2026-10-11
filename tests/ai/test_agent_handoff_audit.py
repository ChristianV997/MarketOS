"""Prose handoff completeness. Synthetic reports only; no live providers."""
from __future__ import annotations

import json

from scripts.ai.agent_output_eval import (
    HANDOFF_SCHEMA,
    SCHEMA,
    audit_handoff,
    audit_handoff_batch,
    evaluate_report,
    main,
)
from scripts.ai.operator_task_packet import validate_packet

BASE = "2965e410c9509368ef256580fbc599e6b025259b"
HEAD = "e4aeebd22179359beaf59b2c7a29d0371e2aa836"
MARKER = "UNIQUE_PROSE_MARKER"
SECRET = "ghp_" + "abcdefghijklmnopqrstuvwxyz12"
CANARY = "CANARY_TOKEN_DO_NOT_STORE"
PAYLOAD = "provider-payload-secret-value"


def _handoff(
    *,
    agent: str = "Grok Chat Agent B",
    lane: str = "agent-handoff-audit",
    base: str = BASE,
    head: str = HEAD,
    include_base: bool = True,
    include_head: bool = True,
    paths: str = "- scripts/ai/agent_output_eval.py\n- tests/ai/test_agent_handoff_audit.py",
    ownership: str = "No ownership conflict.",
    evidence: str = "python -m pytest -q tests/ai/test_agent_handoff_audit.py: 5 passed",
    extra: str = "",
) -> str:
    base_line = f"Base SHA: {base}\n" if include_base else ""
    head_line = f"Head SHA: {head}\n" if include_head else ""
    return (
        f"AGENT_ID: {agent}\n"
        f"LANE: {lane}\n"
        f"{base_line}"
        f"{head_line}"
        "\n"
        "Changed paths:\n"
        f"{paths}\n"
        "\n"
        f"{ownership}\n"
        "\n"
        f"{evidence}\n"
        "This is not merge-ready.\n"
        f"{MARKER} ordinary status update with no authority.\n"
        f"{extra}"
    )


def _rules(document: dict, name: str) -> str:
    return next(item["status"] for item in document["checks"] if item["rule"] == name)


def test_complete_handoff_parses_without_storing_prose():
    document, code = audit_handoff(_handoff())
    assert code == 0
    assert document["schema"] == HANDOFF_SCHEMA
    assert document["overall"] == "passed"
    assert document["merge_ready_claim"] is False
    assert document["merge_authority"] is False
    assert document["agent_id"] == "Grok Chat Agent B"
    assert document["lane"] == "agent-handoff-audit"
    assert document["base_sha"] == BASE
    assert document["head_sha"] == HEAD
    assert document["changed_paths"] == [
        "scripts/ai/agent_output_eval.py",
        "tests/ai/test_agent_handoff_audit.py",
    ]
    assert document["ownership_statement"] == "none"
    dumped = json.dumps(document)
    assert MARKER not in dumped
    assert "ordinary status update" not in dumped


def test_explicit_empty_inventory_is_complete():
    document, code = audit_handoff(_handoff(paths="none"))
    assert code == 0
    assert document["changed_paths"] == []
    assert _rules(document, "missing_changed_paths") == "passed"


def test_omitted_base_sha_is_incomplete_until_a_ready_claim_fails_closed():
    incomplete, incomplete_code = audit_handoff(_handoff(include_base=False))
    assert incomplete_code == 2
    assert incomplete["overall"] == "incomplete"
    assert incomplete["base_sha"] is None
    assert incomplete["head_sha"] == HEAD
    assert _rules(incomplete, "missing_base_sha") == "failed"

    ready = _handoff(include_base=False).replace("This is not merge-ready.", "The branch is merge-ready.")
    failed, failed_code = audit_handoff(ready)
    assert failed_code == 2
    assert failed["overall"] == "failed"
    assert failed["merge_ready_claim"] is True
    assert failed["merge_authority"] is False


def test_nested_heading_does_not_widen_the_changed_path_inventory():
    text = _handoff(
        paths=(
            "- scripts/ai/agent_output_eval.py\n"
            "Compare with tests/ai/test_agent_output_eval.py before editing.\n"
            "### Notes\n"
            "- tests/ai/test_agent_output_eval.py\n"
        )
    )
    document, code = audit_handoff(text)
    assert code == 0
    assert document["changed_paths"] == ["scripts/ai/agent_output_eval.py"]


def test_ambiguous_pass_claim_is_not_backed_by_a_distant_command():
    text = _handoff(
        evidence=(
            "The design review passed.\n"
            "Notes continue for another line.\n"
            "python -m pytest -q tests/ai/test_agent_handoff_audit.py: 5 passed"
        )
    )
    document, code = audit_handoff(text)
    assert code == 2
    assert document["overall"] == "incomplete"
    assert _rules(document, "unproven_test_claim") == "failed"
    assert _rules(document, "false_passed_claim") == "passed"


def test_prefix_siblings_are_not_overlaps_and_duplicate_writers_are():
    left = _handoff(agent="Agent A", lane="lane-a", paths="- scripts/ai/agent_output_eval.py")
    sibling = _handoff(agent="Agent B", lane="lane-b", paths="- scripts/ai_extra/agent_output_eval.py")
    distinct, distinct_code = audit_handoff_batch([left, sibling])
    assert distinct_code == 0
    assert distinct["overlaps"] == []

    duplicate, duplicate_code = audit_handoff_batch([left, _handoff(agent="Agent B", lane="lane-b", paths="- scripts/ai/agent_output_eval.py")])
    assert duplicate_code == 2
    assert duplicate["overall"] == "failed"
    assert duplicate["overlaps"] == [
        {"agents": ["Agent A", "Agent B"], "paths": ["scripts/ai/agent_output_eval.py"]}
    ]

    restated, restated_code = audit_handoff_batch([left, _handoff(agent="Agent A", lane="lane-a", paths="- scripts/ai/agent_output_eval.py")])
    assert restated_code == 0
    assert restated["overlaps"] == []


def test_secret_canary_in_a_path_is_omitted_not_echoed():
    text = _handoff(agent=SECRET, paths=f"- scripts/ai/{CANARY}.py")
    document, code = audit_handoff(text)
    dumped = json.dumps(document)
    assert code == 2
    assert document["overall"] == "failed"
    assert document["agent_id"] is None
    assert document["changed_paths"] == []
    assert _rules(document, "raw_secrets") == "failed"
    assert _rules(document, "canary_content") == "failed"
    assert _rules(document, "unsafe_changed_path") == "failed"
    assert SECRET not in dumped
    assert CANARY not in dumped
    assert "ghp_" not in dumped


def test_missing_identity_is_incomplete_not_malformed():
    text = "We looked at the tooling and will continue tomorrow.\nNo commands were run.\n"
    document, code = audit_handoff(text)
    assert code == 2
    assert document["overall"] == "incomplete"
    assert document["merge_ready_claim"] is False
    for rule in ("missing_agent_id", "missing_lane", "missing_base_sha", "missing_changed_paths", "ownership_unreported"):
        assert _rules(document, rule) == "failed"
    assert "We looked at the tooling" not in json.dumps(document)


def test_merge_ready_claim_fails_closed_without_base_sha():
    text = _handoff(base="not-a-sha")
    text = text.replace("This is not merge-ready.", "The branch is merge-ready.")
    document, code = audit_handoff(text)
    assert code == 2
    assert document["overall"] == "failed"
    assert document["merge_ready_claim"] is True
    assert document["base_sha"] is None
    assert _rules(document, "missing_base_sha") == "failed"


def test_unproven_pass_and_unclear_skip_are_distinct():
    text = _handoff(evidence="5 passed\nci_unavailable")
    document, code = audit_handoff(text)
    assert code == 2
    assert document["overall"] == "incomplete"
    assert _rules(document, "unproven_test_claim") == "failed"
    assert _rules(document, "unclear_skipped_check") == "failed"
    assert _rules(document, "false_passed_claim") == "passed"


def test_false_passed_claim_contradicts_named_unavailable_check():
    text = _handoff(evidence="all checks passed\nhosted test job: ci_unavailable")
    document, code = audit_handoff(text)
    assert code == 2
    assert document["overall"] == "failed"
    assert _rules(document, "false_passed_claim") == "failed"
    assert _rules(document, "unclear_skipped_check") == "passed"


def test_named_skip_with_proven_command_is_not_a_false_pass():
    text = _handoff(
        evidence=(
            "python -m pytest -q tests/ai/test_agent_handoff_audit.py: 5 passed\n"
            "hosted test job: ci_unavailable"
        )
    )
    document, code = audit_handoff(text)
    assert code == 0
    assert document["overall"] == "passed"


def test_same_line_failure_is_not_a_pass():
    text = _handoff(evidence="python -m pytest -q tests/ai/test_agent_handoff_audit.py: 5 passed, 8 failed")
    document, code = audit_handoff(text)
    assert code == 2
    assert document["overall"] == "failed"
    assert _rules(document, "false_passed_claim") == "failed"


def test_named_ownership_conflict_is_not_unreported():
    text = _handoff(ownership="Ownership conflict: scripts/ai/agent_output_eval.py owned by Agent B.")
    document, code = audit_handoff(text)
    assert code == 0
    assert document["ownership_statement"] == "named"
    assert _rules(document, "ownership_unreported") == "passed"


def test_overlapping_write_scopes_are_unreported_when_denied():
    left = _handoff(agent="Agent A", lane="lane-a", paths="- scripts/ai/agent_output_eval.py")
    right = _handoff(agent="Agent B", lane="lane-b", paths="- scripts/ai/")
    document, code = audit_handoff_batch([left, right])
    assert code == 2
    assert document["overall"] == "failed"
    assert document["overlaps"] == [
        {"agents": ["Agent A", "Agent B"], "paths": ["scripts/ai", "scripts/ai/agent_output_eval.py"]}
    ]
    assert _rules(document, "overlapping_write_scope") == "failed"
    assert _rules(document, "unreported_ownership_conflict") == "failed"
    assert MARKER not in json.dumps(document)


def test_sibling_prefixes_do_not_overlap():
    left = _handoff(agent="Agent A", lane="lane-a", paths="- tests/ai/test_agent_handoff_audit.py")
    right = _handoff(agent="Agent B", lane="lane-b", paths="- tests/ai_evil/test_other.py")
    document, code = audit_handoff_batch([left, right])
    assert code == 0
    assert document["overall"] == "passed"
    assert document["overlaps"] == []


def test_secrets_canaries_and_provider_payloads_are_not_stored():
    extra = f"\n{SECRET}\n{CANARY}\n" + '{"access_token": "' + PAYLOAD + '"}\n'
    document, code = audit_handoff(_handoff(extra=extra))
    dumped = json.dumps(document)
    assert code == 2
    assert document["overall"] == "failed"
    for rule in ("raw_secrets", "canary_content", "provider_payload"):
        assert _rules(document, rule) == "failed"
    assert SECRET not in dumped
    assert CANARY not in dumped
    assert PAYLOAD not in dumped
    assert "access_token" not in dumped


def test_cli_reads_handoff_files_and_keeps_structured_reports(tmp_path):
    first = tmp_path / "a.md"
    second = tmp_path / "b.md"
    first.write_text(_handoff(agent="Agent A", lane="lane-a", paths="- tests/ai/test_agent_handoff_audit.py"), encoding="utf-8")
    second.write_text(_handoff(agent="Agent B", lane="lane-b", paths="- docs/ai/PARALLEL_WORK_MATRIX.md"), encoding="utf-8")
    assert main(["--handoff", str(first), "--handoff", str(second), "--json"]) == 0

    packet = validate_packet(
        {
            "agent_id": "grok-ai-development-tooling-engineer",
            "source_chat": "Grok Chat",
            "lane": "AI-CHAT-DEVELOPER-TOOLING-RETROFIT-V1",
            "objective": "Evaluate agent reports",
            "allowed_scope": ["scripts/ai/agent_output_eval.py", "tests/ai/test_agent_handoff_audit.py"],
            "prohibited_scope": ["artifacts/"],
            "base_sha": BASE,
            "worktree": "MarketOS.worktrees/ai-chat-tooling",
            "dependencies": ["MarketOS.AITask.v1"],
            "acceptance_criteria": ["eval fails closed"],
            "selected_tests": ["python -m pytest -q tests/ai/test_agent_handoff_audit.py"],
            "evidence_classification": "actual",
            "rollback": "delete branch",
            "next_action": "review findings",
        }
    )
    report = {
        "claims": ["focused tests passed"],
        "executed_commands": ["python -m pytest -q tests/ai/test_agent_handoff_audit.py"],
        "changed_files": ["scripts/ai/agent_output_eval.py"],
        "pr": 254,
        "rollback": "delete branch",
        "evidence_classification": "actual",
        "check_classifications": {"ruff": "not_run"},
        "status": "incomplete",
    }
    document, code = evaluate_report(report, packet)
    assert SCHEMA == "MarketOS.AgentEval.v1"
    assert code == 0
    assert document["overall"] == "passed"
    assert document["schema"] == SCHEMA
