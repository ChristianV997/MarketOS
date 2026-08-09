# Safe Local Execution Cockpit

The cockpit is the explicit operator boundary between an operating plan and a safe internal MarketOS callable. It resolves tasks into actions, classifies them as executable, advisory/manual, or blocked, and requires approval before local-state-mutating actions run.

## What can run

Only the catalog in `backend/execution_cockpit/action_catalog.py` can dispatch. It covers workflow control, portfolio optimization, operating-plan creation, progress updates, executive intelligence, deliverable generation, validation, pipeline refresh, refinement, and source calibration. All are synchronous internal calls and have no external effects under this boundary.

Evidence acquisition, risk resolution, documentation, and generic manual review remain advisory unless a future explicit safe action is added. Unknown endpoints, missing endpoints, unsafe payloads, blocked tasks, and unsupported action types are refused.

## Approval and checkpoints

Resolving a task persists a `CockpitAction`. The operator can preview a plan without approval. For executable actions, the operator creates a pending approval and explicitly decides `approved` or `rejected`. Execution creates a before/approval checkpoint, invokes one allowlisted callable, records output references, updates the source task status, and creates an after or failure checkpoint. There is no auto-approval.

## Payload safety

Payloads are deep-copied and checked for nested live, spend, publish, send, order, pay, launch, mutation, external URL, secret-like, shell, Python, and arbitrary-execution content. Unknown action types and unknown payload keys are blocked. The cockpit never imports a callable from a request and never executes shell or Python strings.

## Operator workflow

1. Build a portfolio optimization plan.
2. Create an operating plan.
3. `POST /api/cockpit/plans/{plan_id}/preview`.
4. Resolve individual tasks or the plan.
5. Create and decide approvals for executable actions.
6. Execute one action or the approved plan synchronously.
7. Inspect execution checkpoints and produced registry IDs.
8. Create an operations progress review.

`dry_run=true` validates the action and creates a preview execution record without invoking the target callable. Plan execution stops for pending approvals and does not auto-approve.

## Current limitations

- Synchronous only; no background daemon.
- No live business actions, external APIs, or provider operations.
- No arbitrary code or endpoint execution.
- No external calendar, Notion, Slack, Gmail, publishing, payment, supplier, ad, or commerce writes.
- Local registry and configured Obsidian writes are the only persistence side effects.
