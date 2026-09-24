# Approval Governance Conformance

## Purpose

MarketOS has two existing approval controls with different responsibilities.
This contract proves how they compose without creating a third approval
authority or turning an approval record into an execution token.

## Canonical Authorities

- `evaluation/companyos/approval_ledger.py` is the CompanyOS policy and
  simulation authority. It normalizes action types, records required
  conditions, bounds model-spend simulations, and records offline audit
  evidence. It never calls a provider, grants live approval, or executes an
  external action.
- `backend/governance/approval_policy.py` is the backend proposal-governance
  authority. It checks workspace presence and identity consistency, active
  agent status, human review for live requests, and finance/risk review for
  budgets above authority or policy thresholds.
- `backend/organization/planner_executor_reviewer.py` is the existing
  composition seam. It consumes backend governance, forces live-shaped input
  back to a blocked dry-run, and only then calls the registered read-only
  service contract.
- TrustOS and the CompanyOS Approval Ledger remain separate controls. A ledger
  record is evidence for review, not an execution credential or bypass.

## Conformance Invariants

1. External-world actions are blocked or represented only as simulations.
2. CompanyOS status transitions cannot grant live approval in offline mode.
3. Model-spend simulation is bounded by per-run and monthly caps.
4. A missing, blank, or empty workspace identity blocks backend governance.
5. An inactive agent blocks backend governance.
6. Live action requests require human review and remain blocked in this mode.
7. Budget above agent authority requires finance and risk review.
8. Planner live flags force a blocked, not-run, dry-run result.
9. CompanyOS approval records do not become execution permission.
10. Unknown CompanyOS actions normalize to a blocked workflow type.
11. Failed registry quality gates block nonterminal CompanyOS requests.
12. Proposal and workspace identities must match when both are present.
13. Results are deterministic, JSON-safe, and do not reflect secret-like
    values.
14. Workspace identity is carried by backend proposals and governance
    decisions. The CompanyOS ledger is intentionally policy-scoped and is not
    a tenant-authentication authority.
15. No provider, network, payment, order, ad, message, publishing, or CRM
    mutation is enabled by these controls.

## Scope Boundary

This is a conformance contract, not authentication, tenant authorization,
database/RLS enforcement, or a replacement for TrustOS isolation. A future
live capability would still require its own authenticated identity, approved
credentials, budget, policy, and human-review path. The current result is
offline, deterministic, read-only, and simulation-only.

## Validation

Focused contract validation:

```text
python -m pytest tests/contracts/test_approval_governance_conformance.py -q
python -m pytest tests/test_companyos_approval_ledger.py tests/test_approval_policy.py tests/test_local_quality_gate.py -q
```

Adjacent governance, organization, CompanyOS, and TrustOS tests should be run
with the local environment. GitHub Actions results with no runner, no steps,
or unavailable logs are `ci_unavailable`, not passes.
