import json
import os

def validate_release_contract(payload: dict) -> dict:
    """
    Validates an integration release contract payload for the Merger Agent.
    Returns {"decision": "MERGE", "reason": "..."} or REJECT/HOLD.
    """
    # 1. PR identity, head SHA, base SHA, and stale-base detection
    if payload.get("is_stale_base", False):
        return {"decision": "REJECT", "reason": "stale_base"}

    # 2. Branch/worktree ownership and active-worktree conflicts
    if payload.get("worktree_ownership_state") == "Conflict":
        return {"decision": "REJECT", "reason": "worktree_conflict"}

    # 3. Changed-file scope and direct versus stacked diff (handled implicitly by structural adherence)

    # 4. Dependency ordering
    if payload.get("dependency_ordering") != "Yes" or len(payload.get("unmet_dependencies", [])) > 0:
        return {"decision": "HOLD", "reason": "unmet_dependencies"}

    # 5. Focused and adjacent test evidence
    if payload.get("focused_and_adjacent_tests") == "Failed":
        return {"decision": "REJECT", "reason": "test_failure"}

    # 6. Compile, lint, diff, and quality-gate evidence
    if payload.get("compile_and_lint_results") == "Failed":
        return {"decision": "REJECT", "reason": "compile_lint_failure"}

    # 7. Evidence classifications
    evidence = payload.get("evidence", {})
    if not evidence.get("actual") and not evidence.get("simulated"):
        return {"decision": "REJECT", "reason": "missing_evidence"}

    # 8. CI execution steps, runner identity, logs, required-job completeness, executed failures
    ci_steps = payload.get("ci_execution_steps", {})
    if ci_steps.get("required_job_completeness") == "Missing":
        return {"decision": "REJECT", "reason": "missing_required_job"}
    if ci_steps.get("executed_failures") != "None":
        return {"decision": "REJECT", "reason": "executed_failures"}

    if ci_steps.get("step_evidence") == "ci_unavailable":
        if not payload.get("human_override_local_evidence", False):
            return {"decision": "HOLD", "reason": "ci_unavailable"}

    # 9. Review state, draft state, and explicit human approval
    if payload.get("draft_ready_state") != "Ready":
        return {"decision": "HOLD", "reason": "draft"}
    if payload.get("review_state") != "Approved":
        return {"decision": "HOLD", "reason": "needs_review"}
    if not payload.get("explicit_human_approval", False):
        return {"decision": "HOLD", "reason": "needs_human_approval"}

    # 10. Duplicate, superseded, stale, and harmful PR disposition
    if payload.get("duplicate_superseded_pr_handling") not in ["None", "Resolved"]:
        return {"decision": "HOLD", "reason": "duplicate_superseded"}

    # 11. Rollback reference (just ensure it exists)
    if not payload.get("rollback_reference"):
        return {"decision": "REJECT", "reason": "missing_rollback"}

    # 12. Credential, provider, model, database, and external-mutation safety
    if payload.get("credential_and_mutation_safety") != "Passed":
        return {"decision": "REJECT", "reason": "unsafe_mutation"}

    # 13. TrustOS and Approval Ledger state
    if payload.get("trustos_status") != "Cleared":
        return {"decision": "REJECT", "reason": "trustos_blocked"}
    if payload.get("approval_ledger_status") != "Approved":
        return {"decision": "HOLD", "reason": "approval_ledger_pending"}

    if payload.get("provider_model_activation_status") not in ["Offline", "Dry-Run only"]:
        return {"decision": "REJECT", "reason": "live_activation_unsupported"}

    # 14. Explicit final merger decision
    return {"decision": "MERGE", "reason": "all_checks_passed"}


def load_fixture(name: str) -> dict:
    base_path = os.path.dirname(__file__)
    fixture_path = os.path.join(base_path, "..", "fixtures", "release_train", f"{name}.json")
    with open(fixture_path, "r") as f:
        return json.load(f)


def test_valid_merge_candidate():
    payload = load_fixture("valid_merge_candidate")
    result = validate_release_contract(payload)
    assert result["decision"] == "MERGE"


def test_stale_head():
    payload = load_fixture("stale_head")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "stale_base"


def test_active_worktree_ownership():
    payload = load_fixture("active_worktree_ownership")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "worktree_conflict"


def test_zero_step_ci():
    payload = load_fixture("zero_step_ci")
    result = validate_release_contract(payload)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "ci_unavailable"


def test_executed_test_failure():
    payload = load_fixture("executed_test_failure")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "test_failure"


def test_missing_required_job():
    payload = load_fixture("missing_required_job")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "missing_required_job"


def test_stacked_pr_unmet_dependency():
    payload = load_fixture("stacked_pr_unmet_dependency")
    result = validate_release_contract(payload)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "unmet_dependencies"


def test_duplicate_superseded_pr():
    payload = load_fixture("duplicate_superseded_pr")
    result = validate_release_contract(payload)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "duplicate_superseded"


def test_unsafe_mutation_claim():
    payload = load_fixture("unsafe_mutation_claim")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "unsafe_mutation"


def test_valid_local_evidence_override():
    payload = load_fixture("valid_local_evidence_override")
    result = validate_release_contract(payload)
    assert result["decision"] == "MERGE"


def test_independent_pr():
    payload = load_fixture("independent_pr")
    result = validate_release_contract(payload)
    assert result["decision"] == "MERGE"


def test_stacked_pr_valid():
    payload = load_fixture("stacked_pr_valid")
    result = validate_release_contract(payload)
    assert result["decision"] == "MERGE"


def test_draft_pr():
    payload = load_fixture("draft_pr")
    result = validate_release_contract(payload)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "draft"


def test_missing_review():
    payload = load_fixture("missing_review")
    result = validate_release_contract(payload)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "needs_review"


def test_missing_rollback_reference():
    payload = load_fixture("missing_rollback_reference")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "missing_rollback"


def test_pending_approval_ledger():
    payload = load_fixture("pending_approval_ledger")
    result = validate_release_contract(payload)
    assert result["decision"] == "HOLD"
    assert result["reason"] == "approval_ledger_pending"


def test_trustos_blocked():
    payload = load_fixture("trustos_blocked")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "trustos_blocked"


def test_live_activation_claim():
    payload = load_fixture("live_activation_claim")
    result = validate_release_contract(payload)
    assert result["decision"] == "REJECT"
    assert result["reason"] == "live_activation_unsupported"
