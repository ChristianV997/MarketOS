# SaaS margin policy

The hard rules `backend/stack_planner` enforces so a client stack is never
recommended a paid tool that costs more than the margin it protects. These
rules are code (`backend/stack_planner/recommendations.py`), not just
prose — this document explains the reasoning behind each one.

## Principle

> MarketOS should choose the cheapest sufficient stack, coordinate it,
> measure profitability, and prevent clients from paying for tools that do
> not produce money.

Every gate below exists because a fixed monthly SaaS cost that isn't
justified by revenue is a direct, avoidable hit to a client's contribution
margin — the same quantity `backend.validation.margin_calculator` and
`backend.ledger` already exist to protect.

## The gates

| Provider | Gate | Function | Rationale |
|---|---|---|---|
| Shopify | Blocked when `margin_sensitivity == "low_cost_validation"` | `shopify_allowed_over_woo` | $39+/mo fixed cost isn't justified when WooCommerce (free) is functionally sufficient and the business hasn't validated demand yet |
| GoHighLevel | Blocked below its cheapest plan's `min_monthly_revenue_usd` (from the Provider Registry catalog) | `gohighlevel_allowed` | $97+/mo fixed cost needs revenue to amortize against; recommending it pre-revenue is recommending a loss |
| n8n | Always blocked for `is_white_labeled_client_facing=True` | `n8n_allowed` | Not a margin gate — a licensing/governance gate (n8n is internal-only per `docs/oss/LICENSE_MANIFEST.yml`); listed here because it's enforced the same way |
| Postiz | Blocked without `postiz_legal_approval=True` | `postiz_allowed` | AGPL-3.0 — a legal-review gate, not a cost gate, enforced identically |

## Threshold selection

Revenue thresholds come directly from `backend/providers/provider_catalog.py`'s
`ProviderPlan.min_monthly_revenue_usd` — not hardcoded in the planner. To
change a threshold, edit the catalog entry; the gate logic reads it live.

## What this policy does not do

- It does not cap what a client is *charged* — `backend.costs.stack_total.break_even_client_price`
  computes the minimum viable price, not a maximum.
- It does not forbid choosing a more expensive stack when the request
  explicitly justifies it (`margin_sensitivity="premium_brand"`, an
  existing Shopify store, revenue clearing a threshold) — the policy blocks
  *unjustified* cost, not all cost.
- It does not apply retroactively to a workspace's existing stack —
  `backend.stack_planner` is advisory only (see `docs/STACK_PLANNER.md`);
  it never mutates a live integration or forces a migration.

## Extending the policy

Add a new predicate function to `backend/stack_planner/recommendations.py`
(matching `gohighlevel_allowed`'s shape: a pure function of
`BusinessStackRequest` returning `bool`), wire it into the relevant
`build_*_recommendation` function so a blocked provider is still surfaced
with `blocked=True` + `blocked_reason` (never silently omitted), and add a
test asserting both the blocked and allowed paths in
`tests/test_stack_planner/test_planner.py`.
