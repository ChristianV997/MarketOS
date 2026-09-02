# MarketOS Integration Release Contract

This release contract defines the exact governance conditions required before integrating external capabilities and merging dependent MarketOS vertical feature branches.

## Explicit Acceptance Fields
Every automated or manual merge request MUST evaluate and record the following payload of contract fields:

```json
{
  "pr_identity": "PR Number and Title",
  "head_sha": "Exact PR HEAD SHA",
  "base_sha": "Exact Target Base SHA",
  "worktree_ownership_state": "Valid/Conflict (Cannot overwrite dirty operator worktrees)",
  "changed_file_scope": "List of affected components",
  "dependency_ordering": "Adheres to PR_DEPENDENCY_RELEASE_TRAIN (Yes/No)",
  "focused_and_adjacent_tests": "Passed/Failed",
  "compile_and_lint_results": "Passed/Failed",
  "evidence": {
    "actual": "...",
    "simulated": "...",
    "unavailable": "...",
    "not_run": "..."
  },
  "ci_execution_step_evidence": "All steps executed vs 0-step outage",
  "review_state": "Approved/ChangesRequested",
  "draft_ready_state": "Ready/Draft",
  "rollback_reference": "Known-good SHA",
  "duplicate_superseded_pr_handling": "List of PRs to close",
  "credential_and_mutation_safety": "Passed (No live networks/No Git secrets)",
  "trustos_status": "Cleared/Blocked",
  "approval_ledger_status": "Approved/Pending",
  "provider_model_activation_status": "Offline/Dry-Run only",
  "final_merger_agent_decision": "MERGE / REJECT / HOLD"
}
```

## 1. Current-Head Verification
Before merging, the Merger Agent must verify the explicit live SHA of both the PR branch and `main`. Merges executed against stale references are invalid.

## 2. Base/Head and Three-Dot Diff Checks
Merges require a cleanly resolved base. `git diff base...head` must contain exactly the authorized paths, introducing no unintended cross-vertical code.

## 3. Worktree Ownership
Detached validation worktrees are considered evidence only, not active ownership. A PR must not overwrite or conflict with a dirty worktree actively owned by a human operator without explicit handoff.

## 4. Focused and Adjacent Validation
Each integration must run focused unit/integration tests for its own logic, plus adjacent validation (e.g., architecture boundaries, security policies, and broader test suites) to ensure no regressions.

## 5. Baseline-Versus-Regression Comparison
- **Baseline failures** (defects already present in `main`) must be isolated and repaired in dedicated upstream PRs.
- **PR Regressions** (defects introduced by the PR) strictly block the PR until repaired. Feature branches must not absorb unrelated baseline repairs.

## 6. CI States
The following states dictate the automated merge outcome:
- **passed**: Deterministic execution success (Merge allowed).
- **failed**: Executed failure. Cannot be bypassed mechanically.
- **unavailable**: Required check missing entirely.
- **timed_out**: Execution exceeded configured bounds.
- **not_run**: Skipped due to configuration or dependency.
- **collection_failed**: Evidence gathering error.
- **blocked**: Upstream dependency unmet.
- **malformed**: Invalid syntax, YAML, or structure.
- **ci_unavailable**: Zero-step runner outage. (Requires explicit manual human override with localized evidence to bypass).

## 7. Security and Secret Scanning
Integrations must pass all TrustOS security scanners, Semgrep policies, and container-smoke phases. No secrets may be added to Git; all credentials must be routed through the central registry.

## 8. External-Capability Provenance/License Review
All external capabilities must declare origin, maintainer, and licensing in accordance with the `EXTERNAL_CAPABILITY_INTEGRATION_TEMPLATE.md`.

## 9. TrustOS Gates
Integrations must clear offline TrustOS privacy, security, and compliance scanners. Any failure requires professional review and remediation.

## 10. Approval Ledger State
Live external mutations, automated publishing, and sales outreach require an explicit Approval Ledger record (operator sign-off) prior to execution.

## 11. Resource Governor Budget/Quota State
Integrations (especially models and external providers) must fall within hard spending, quota, and runaway limits defined by the Resource & Execution Governor.

## 12. Client Workspace Boundary
External capabilities must enforce Client Workspace isolation. Payloads must not cross-pollinate, and cross-client data must not leak in generalized exports.

## 13. Stack Dependency Recalculation After Each Merge
Following a merge, any vertically stacked PRs (e.g., #214 stacked on #213) must be immediately rebased, and their CI baseline states recalculated.

## 14. Duplicate/Superseded PR Closure
Upon merging an integration, any duplicate or superseded capabilities aiming to solve the identical business outcome must be closed immediately.

## 15. Rollback Order
The deployment must specify an exact, known-good base SHA to revert to if catastrophic regressions are detected post-merge.

## 16. Explicit Human/Admin Bypass Recording
Any automated gate bypass (such as overriding `ci_unavailable` with local evidence) must be permanently logged in the PR with explicit human operator authorization.
