# DAO-future architecture (documentation only — no blockchain execution)

This document describes how MarketOS's existing foundations (built in
earlier phases: `backend/workspaces/`, `backend/experiments/`,
`backend/contracts/`, `backend/risk/`, `backend/metrics/attribution.py`)
could extend into a DAO-style business-automation governance layer later.
**Nothing in this document is implemented as executable behavior.** No
tokenomics, no blockchain dependency, no smart contract, no on-chain
anything. The mapping below is deliberately built on concepts that already
exist and already work, so that if this is ever pursued, it extends real
infrastructure rather than starting from zero.

## Why now, and why only a document

The task that requested this explicitly said: *"do not implement
blockchain execution"* and *"future DAO abstractions can be represented as
interfaces or placeholder schemas only if clean and non-invasive."*
Building real governance/voting/token machinery is a multi-month
undertaking with real legal, security, and financial-custody implications
— entirely out of scope for a documentation pass. What follows is (a) a
conceptual mapping to existing code, and (b) a small set of placeholder
dataclasses (`backend/dao_future/schemas.py`) that exist purely as typed
references for future design work — they are not imported by any live code
path, not persisted, not registered anywhere, and have zero runtime effect.

## Concept mapping: DAO abstraction → existing MarketOS foundation

| DAO concept | Maps to (already built, already real) | Gap to close for a real DAO layer |
|---|---|---|
| **BusinessCell** | `backend.workspaces.client_workspace.ClientWorkspace` — already isolates data, credentials, budget ceilings, and mode per tenant. | Add a governance model (who can propose/vote for this cell) and an on/off switch per service module (see "Modules can be enabled/disabled per cell" below). |
| **Proposal** | `backend.experiments.envelope.CommercialRunEnvelope` — already a durable, auditable "here's what we're proposing to do and why" record (`inputs`, `mode`, `status`). | Add a proposal-specific status flow (`proposed → voting → approved/rejected → executing`) distinct from the envelope's current `created/running/completed/blocked/failed` lifecycle, which describes execution, not deliberation. |
| **Evidence** | The `CommercialRunEnvelope` itself once completed — `outputs`, `actual_spend`, `audit_log_refs` (pointing into `backend.orchestration.event_store`) already constitute a full evidence trail for what actually happened. | Nothing structural — this mapping is close to a direct match already. |
| **GovernanceDecision** | Nothing yet. Closest existing analog: `agents/arbitration.py`'s RiskAgent-veto-wins arbitration between competing automated agents — a *machine* governance mechanism, not a human/DAO one. | Build a human-approval record type distinct from arbitration: who approved, what threshold/quorum was met, when. |
| **CapitalAllocationRequest** | `backend.decision.capital_policy.allocate_capital` (the sanctioned QP-based allocator) + `backend.risk.gate.check_spend` (the real spend gate) already decide *how much* budget an experiment gets and whether it's currently allowed to spend. | A DAO layer would need to gate the *allocator's own inputs* behind a governance decision — i.e., "the cell's total budget for this quarter" becomes a voted-on number, not an env-var constant. |
| **OperatorRole** | Nothing yet — today there is no concept of a human "operator" attached to a workspace at all; `ClientWorkspace.owner_label` is a free-text string, not a role/permission model. | Needs real authn/authz — out of scope for a documentation pass, flagged explicitly in `docs/SERVICE_MODULES.md`'s SaaS-lite readiness notes. |
| **RevenueShareRule** | `services.ecommerce_operator.contribution_profit.reconcile_contribution_profit` already computes an audited, ground-truth-reconciled `contribution_profit` per experiment — exactly the number a revenue-share rule would need to reference. | Add a rule schema (`share_pct` per operator/role, applied to `contribution_profit`) and a settlement record — no real payment execution implied, just an audited "who is owed what" ledger entry. |

## The eight DAO capabilities this task asked to be mapped

1. **Workspaces become business cells.** Direct rename/extension of `ClientWorkspace` — no structural change needed, just an added governance sub-model.
2. **Experiments become proposals.** `CommercialRunEnvelope`'s existing `status` lifecycle would grow a pre-execution deliberation phase (see table above).
3. **Run envelopes become evidence.** Already true today — `envelope.outputs` + `audit_log_refs` are exactly this.
4. **Capital allocation decisions become governable actions.** The *decision of how much a cell gets to allocate* becomes vote-gated; the allocator math itself (`allocate_capital`) doesn't need to change.
5. **Human approvals become voting or delegated authority.** New concept (`GovernanceDecision`), not yet built.
6. **Profit-sharing can be attached to audited contribution-profit records.** `reconcile_contribution_profit`'s output is already the right audited number to attach a `RevenueShareRule` to.
7. **Modules can be enabled/disabled per cell.** New field needed on `ClientWorkspace` (e.g. `enabled_services: list[str]`) — additive, doesn't break existing default (all services available).
8. **Operators can propose campaigns/products/automations/budgets, and the system records outcomes and updates reputation/permissions.** Directly composes `Proposal` + `Evidence` + a new reputation-tracking mechanism (doesn't exist yet — would likely live alongside `backend.economics.supplier_feedback`'s existing EMA-based reliability-scoring pattern, applied to operators instead of suppliers).

## Placeholder schemas (non-invasive, zero runtime effect)

`backend/dao_future/schemas.py` defines six dataclasses matching the task's
required names exactly: `BusinessCell`, `Proposal`, `GovernanceDecision`,
`CapitalAllocationRequest`, `OperatorRole`, `RevenueShareRule`. Every field
is a plain type (str/float/list/dict) — no relationships are enforced, no
validation logic exists, and nothing in the live codebase imports this
module. It exists solely so a future implementation has an agreed-upon
starting vocabulary rather than reinventing field names from scratch.

## What this explicitly does not include

- No token, no wallet, no smart contract, no on-chain transaction of any kind.
- No real voting mechanism (quorum counting, weighted votes, delegation) — only the placeholder shape of a decision record.
- No real reputation/permission engine — only a named gap in the mapping table above.
- No enforcement: nothing prevents a workspace today from doing anything a "cell" concept would eventually gate. This is a design document, not a security boundary.
