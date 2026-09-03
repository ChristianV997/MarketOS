# MarketOS Integration Release Contract

This release contract defines the exact governance conditions required before integrating external capabilities and merging dependent MarketOS vertical feature branches.

## Explicit Acceptance Fields
Every automated or manual merge request MUST evaluate and record the following payload of contract fields:

```json
{
  "pr_identity": "PR Number and Title",
  "head_sha": "Exact PR HEAD SHA",
  "base_sha": "Exact Target Base SHA",
  "is_stale_base": false,
  "worktree_ownership_state": "Valid/Conflict (Cannot overwrite dirty operator worktrees)",
  "changed_file_scope": "List of affected components",
  "diff_type": "Direct vs Stacked",
  "dependency_ordering": "Adheres to PR_DEPENDENCY_RELEASE_TRAIN (Yes/No)",
  "unmet_dependencies": [],
  "focused_and_adjacent_tests": "Passed/Failed",
  "compile_and_lint_results": "Passed/Failed",
  "evidence": {
    "actual": "...",
    "simulated": "...",
    "unavailable": "...",
    "not_run": "..."
  },
  "ci_execution_steps": {
    "runner_identity": "local/github",
    "required_job_completeness": "Passed/Missing",
    "executed_failures": "None",
    "step_evidence": "All steps executed vs 0-step outage"
  },
  "review_state": "Approved/ChangesRequested",
  "draft_ready_state": "Ready/Draft",
  "explicit_human_approval": true,
  "duplicate_superseded_pr_handling": "List of PRs to close",
  "rollback_reference": "Known-good SHA",
  "credential_and_mutation_safety": "Passed (No live networks/No Git secrets)",
  "credential_boundary_status": "Intact/Missing",
  "export_safety": "Safe/Unsafe",
  "learning_evidence_status": "Complete/Incomplete",
  "trustos_status": "Cleared/Blocked",
  "approval_ledger_status": "Approved/Pending",
  "provider_model_activation_status": "Offline/Dry-Run only",
  "human_override_local_evidence": false,
  "provenance_and_license_verified": true,
  "capability_promotion_lifecycle": {
    "discovered": true,
    "provenance_reviewed": true,
    "license_reviewed": true,
    "fixture_tested": true,
    "manually_validated": true,
    "integration_tested": true,
    "approved_for_future_activation": true
  },
  "final_merger_agent_decision": "MERGE / REJECT / HOLD"
}
```

## Public Release-Engineering Patterns Adapted
This contract adapts bounded governance concepts from mature projects (e.g., Kubernetes contribution checks, Apache release policies, OpenTelemetry governance):
- **Evidence Provenance:** Mislabeled simulated evidence masquerading as "actual" is deterministically trapped and rejected.
- **Human Override vs Executed Failures:** `ci_unavailable` states hold a PR securely. A documented local-evidence override (`human_override_local_evidence: true`) permits a merge bypassing unavailability, but it **never** hides or bypasses an executed test failure.
- **Dependency Release Trains:** Stacked pull requests enforce strict precedence.
- **Rollback References & Ownership:** Explicit git SHA bases and ownership conflict checks prevent dirty-tree corruption.

## 1. PR Identity, Head SHA, Base SHA, and Stale-Base Detection
Before merging, the Merger Agent must verify the explicit live SHA of both the PR branch and `main`. Merges executed against stale references (`is_stale_base = true`) are invalid and rejected.

## 2. Branch/Worktree Ownership and Active-Worktree Conflicts
Detached validation worktrees are considered evidence only. A PR must not overwrite or conflict with a dirty worktree actively owned by a human operator without explicit handoff (`worktree_ownership_state = Valid`).

## 3. Changed-File Scope and Direct Versus Stacked Diff
Merges require a cleanly resolved base. `git diff base...head` must contain exactly the authorized paths, introducing no unintended cross-vertical code. The contract distinguishes between a direct diff against `main` and a stacked diff against an upstream PR.

## 4. Dependency Ordering
All merges must follow the explicit train defined in `PR_DEPENDENCY_RELEASE_TRAIN.md` (quality → security → frontend/API → development environment → research adapters → commerce operations → evidence integrity → Learning Ledger). Stacked PRs with unmet dependencies will be held.

## 5. Focused and Adjacent Test Evidence
Each integration must run focused unit/integration tests for its own logic, plus adjacent validation (architecture boundaries, security policies, etc.) to ensure no regressions.

## 6. Compile, Lint, Diff, and Quality-Gate Evidence
Must pass `compileall`, linting tools (`ruff`), and explicit difference checks (`git diff --check`). The quality-gate evidence must be formally logged.

## 7. Actual, Simulated, Unavailable, and Not_Run Classifications
- **actual**: Executed live network tests (Requires Approval Ledger).
- **simulated**: Executed dry-run/mock tests (Default).
- **unavailable**: Required check missing entirely.
- **not_run**: Skipped due to configuration or operator intent.

## 8. CI Execution Steps, Runner Identity, Logs, Required-Job Completeness, and Executed Failures
Must identify the runner and confirm that all required jobs executed successfully. Missing required jobs or executed test failures strictly block the PR. Zero-step CI outages (`ci_unavailable`) must be bypassed only via explicit local evidence overrides, avoiding the requirement for impossible evidence.

## 9. Review State, Draft State, and Explicit Human Approval
PRs must be in a "Ready" state. Explicit human approval or an authorized Merger Agent proxy approval is required.

## 10. Duplicate, Superseded, Stale, and Harmful PR Disposition
Upon merging an integration, any duplicate, stale, superseded, or harmful capabilities aiming to solve the identical business outcome must be closed immediately based on the contract payload.

## 11. Rollback Reference
The deployment must specify an exact, known-good base SHA to revert to if catastrophic regressions are detected post-merge.

## 12. Credential, Provider, Model, Database, and External-Mutation Safety
No secrets may be added to Git; all credentials must be routed through the central registry. Must enforce Client Workspace isolation and ensure zero unintended provider/database mutations. `credential_boundary_status` and `export_safety` must be fully resolved.

## 13. TrustOS, Capability Lifecycle, and Approval Ledger State
Integrations must clear offline TrustOS privacy and security scanners. Live external mutations require an explicit Approval Ledger record. A tracked capability must document its strict `capability_promotion_lifecycle` prior to activation, and live activation remains exclusively blocked unless approved.

## 14. Explicit Final Merger Decision
The contract must culminate in a deterministic decision: `MERGE`, `REJECT`, or `HOLD`.
