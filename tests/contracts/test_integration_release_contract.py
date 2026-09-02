import json
import pytest

def validate_release_contract(payload: dict) -> str:
    """
    Validates an integration release contract payload for the Merger Agent.
    Returns 'MERGE', 'REJECT', or 'HOLD'.
    """
    # 1. Reject malformed handoffs
    required_keys = [
        "pr_identity", "head_sha", "base_sha", "worktree_ownership_state",
        "changed_file_scope", "dependency_ordering", "focused_and_adjacent_tests",
        "compile_and_lint_results", "evidence", "ci_execution_step_evidence",
        "review_state", "draft_ready_state", "rollback_reference",
        "duplicate_superseded_pr_handling", "credential_and_mutation_safety",
        "trustos_status", "approval_ledger_status", "provider_model_activation_status"
    ]
    for key in required_keys:
        if key not in payload:
            return "REJECT_MALFORMED"

    # 2. Check stale heads / duplicate ownership
    if payload["worktree_ownership_state"] == "Conflict":
        return "REJECT_OWNERSHIP_CONFLICT"
    
    if payload.get("is_stale_head", False):
        return "REJECT_STALE_HEAD"

    # 3. Missing evidence
    evidence = payload.get("evidence", {})
    if not evidence.get("actual") and not evidence.get("simulated"):
        return "REJECT_MISSING_EVIDENCE"

    # 4. Check draft state and dependency ordering
    if payload["draft_ready_state"] != "Ready":
        return "HOLD_DRAFT"
    if payload["dependency_ordering"] != "Yes":
        return "HOLD_DEPENDENCY_ORDER"

    # 5. Failed checks and Zero-Step CI logic
    if payload["focused_and_adjacent_tests"] == "Failed" or payload["compile_and_lint_results"] == "Failed":
        return "REJECT_EXECUTED_FAILURE"

    if payload["ci_execution_step_evidence"] == "ci_unavailable":
        # Can only bypass if local evidence explicitly overrides
        if not payload.get("human_override_local_evidence", False):
            return "HOLD_CI_UNAVAILABLE"
            
    # 6. Unsafe merge claims (TrustOS, Credentials, Mutations)
    if payload["credential_and_mutation_safety"] != "Passed":
        return "REJECT_UNSAFE_MUTATION"
    if payload["trustos_status"] != "Cleared":
        return "REJECT_TRUSTOS_BLOCKED"
    if payload["approval_ledger_status"] != "Approved":
        return "HOLD_APPROVAL_LEDGER"
    if payload["provider_model_activation_status"] not in ["Offline", "Dry-Run only"]:
        return "REJECT_LIVE_ACTIVATION"

    return "MERGE"


def test_malformed_handoff():
    payload = {"pr_identity": "#123"}
    assert validate_release_contract(payload) == "REJECT_MALFORMED"

def test_stale_head_and_ownership():
    payload = get_valid_payload()
    payload["worktree_ownership_state"] = "Conflict"
    assert validate_release_contract(payload) == "REJECT_OWNERSHIP_CONFLICT"
    
    payload["worktree_ownership_state"] = "Valid"
    payload["is_stale_head"] = True
    assert validate_release_contract(payload) == "REJECT_STALE_HEAD"

def test_missing_evidence():
    payload = get_valid_payload()
    payload["evidence"] = {"unavailable": "true"}
    assert validate_release_contract(payload) == "REJECT_MISSING_EVIDENCE"

def test_failed_checks_executed_failures():
    payload = get_valid_payload()
    payload["focused_and_adjacent_tests"] = "Failed"
    assert validate_release_contract(payload) == "REJECT_EXECUTED_FAILURE"

def test_zero_step_ci():
    payload = get_valid_payload()
    payload["ci_execution_step_evidence"] = "ci_unavailable"
    assert validate_release_contract(payload) == "HOLD_CI_UNAVAILABLE"
    
    payload["human_override_local_evidence"] = True
    assert validate_release_contract(payload) == "MERGE"

def test_unsafe_merge_claims():
    payload = get_valid_payload()
    payload["trustos_status"] = "Blocked"
    assert validate_release_contract(payload) == "REJECT_TRUSTOS_BLOCKED"
    
    payload["trustos_status"] = "Cleared"
    payload["provider_model_activation_status"] = "Live"
    assert validate_release_contract(payload) == "REJECT_LIVE_ACTIVATION"
    
    payload["provider_model_activation_status"] = "Dry-Run only"
    payload["credential_and_mutation_safety"] = "Failed"
    assert validate_release_contract(payload) == "REJECT_UNSAFE_MUTATION"

def test_valid_merge():
    payload = get_valid_payload()
    assert validate_release_contract(payload) == "MERGE"


def get_valid_payload():
    return {
        "pr_identity": "#999 Test",
        "head_sha": "abc1234",
        "base_sha": "def5678",
        "worktree_ownership_state": "Valid",
        "changed_file_scope": ["src/app.py"],
        "dependency_ordering": "Yes",
        "focused_and_adjacent_tests": "Passed",
        "compile_and_lint_results": "Passed",
        "evidence": {
            "simulated": "Mock evidence present"
        },
        "ci_execution_step_evidence": "All steps executed",
        "review_state": "Approved",
        "draft_ready_state": "Ready",
        "rollback_reference": "def5678",
        "duplicate_superseded_pr_handling": "None",
        "credential_and_mutation_safety": "Passed",
        "trustos_status": "Cleared",
        "approval_ledger_status": "Approved",
        "provider_model_activation_status": "Offline",
        "final_merger_agent_decision": ""
    }
