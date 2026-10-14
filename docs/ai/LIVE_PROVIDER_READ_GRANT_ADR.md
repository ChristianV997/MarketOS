# ADR: Research Read Grant Contract (Decision Seam Only)

- Status: Proposed. Implemented as a tested decision seam. Not wired to any runtime path.
- Date: 2026-10-14
- Module: `evaluation/companyos/research_read_grant.py`
- Tests: `tests/contracts/test_research_read_grant_contract.py`

## Context

- `evaluation/companyos/approval_ledger.py` is the canonical offline policy and simulation gate. It refuses `approved` through `transition_status` and through serialized input.
- `evaluation/companyos/credential_registry.py` is metadata-only. It holds references, scopes, capabilities, budgets, and health state, never secret values. Every default credential is `needed`.
- No trusted server-side grant store or verified approval identity exists on `main`.
- `backend/governance/approval_policy.py` detects human review by substring match on `decided_by_agent_id`. That is not a verified identity, so this seam does not use it as approval evidence.

## Decision

1. The contract lives in a new module. It imports the canonical policy table, capability records, and credential references. It duplicates none of them and changes neither canonical module.
2. Reads and mutations are split by allowlist. Only `web_data_acquisition` can be a read grant, because the canonical policy allows later approval for it with zero spend and a `human_operator` approver. Every other request type is `request_type_not_grantable`, including `provider_call`, outreach, payment, publish, order, ad launch, CRM, vector indexing, and model spend. Non-read side effects are denied.
3. A grant binds to:
   - the verified workspace (passed by the server, never taken from the request body)
   - the approval request ID
   - the canonical policy ID
   - provider and capability
   - a credential reference that must be `active_reference_only` in the registry
   - exact scope IDs, fields, and regions
   - a purpose code
   - per-run and monthly caps, where canonical zero caps dominate
   - a per-window request cap
   - terms and privacy review references
   - retention of 1 to 30 days
   - a TTL of at most 7 days
   - revocation
   - an approver ID and role
4. Authority is a caller-supplied `GrantAuthority` protocol with `verify` and `usage`. Without one, the status is `not_wired`. An authority that raises produces `blocked`. This repository has no production implementation.
5. Serialized input is data. `read_grant_from_mapping` rejects unknown keys, so `status`, `approved`, `approval_status`, `authority`, and `server_verified` claims cannot enter. A payload cannot approve itself.
6. Reporting is sanitized. Reasons come from a fixed vocabulary (`DECISION_REASONS`). Validation errors never echo input values, and secret-like values are rejected by the registry's own `_secret_like` check.

## Status Vocabulary

- `contract_satisfied`: every binding passed and the authority verified the grant. This is not runtime permission.
- `blocked`: at least one binding or cap failed.
- `not_wired`: every contract check passed but no authority exists. This is the only result a valid grant can produce in this repository.
- `authorize_research_read` is the runtime entry point. It always passes `authority=None`, so it never returns `contract_satisfied`.

## Consequences

- Nothing executes. There are no provider calls, no network access, no secret reads, and no persistence.
- `now` and `verified_workspace_id` are trusted only because the caller supplies them. A future wiring must take both from the server clock and the authenticated request context, never from the request body.
- Activating any read requires separately reviewed work: a trusted grant store, identity-verified human approval, usage counters, revocation propagation, and review of the terms and privacy references.
- A credential moves to `active_reference_only` only through its own reviewed registry path. This seam does not do that.
- `FakeAuthority` exists only inside the test module.

## Open Items

- Owner to confirm the purpose codes (`market_research`, `evidence_review`), the 7-day TTL ceiling, and the 30-day retention ceiling.
- `docs/ai/CANONICAL_PATHS.md` does not list the new module yet. Adding it would conflict with open PRs #474 and #475, which also edit that file. Add the row at merge time.
- `backend/governance/approval_policy.py` approver detection uses substring matching on `decided_by_agent_id`. This predates this lane and needs an owner. It is not changed here.
- Rate-window accounting belongs to the authority. The seam only compares the counts it is given.
