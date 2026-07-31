# Live-mode safety

The gate every live external mutation or real spend must pass, and how it
composes with this repo's pre-existing money-safety guardrails. Defined in
`backend/workspaces/live_mode_checklist.py`.

## The rule

> No code should spend real ad budget, create live campaigns, contact real
> customers, send outbound messages, publish content, place supplier
> orders, or mutate third-party production resources unless every one of
> the checklist items below passes.

This is not a new invention — it's the same posture already proven
throughout this codebase (`TIKTOK_DRY_RUN`, `META_DRY_RUN`,
`STORE_DRY_RUN`, `SUPPLIERS_DRY_RUN`, `ADLIB_DRY_RUN` all default `true`,
per the README's "Everything is dry-run by default" section) — formalized
into one reusable checklist for the new service-module layer.

## The checklist

`backend.workspaces.live_mode_checklist.check(workspace, integration, *, proposed_amount=0.0)`
never raises; it always returns a structured result:

```python
{
    "allowed": bool,
    "blocked_reasons": [...],
    "checklist": {
        "live_mode_enabled": bool,       # workspace.live_mode_enabled
        "credential_configured": bool,   # backend.workspaces.credential_scope
        "integration_allowed": bool,     # workspace.allowed_integrations
        "within_monthly_ceiling": bool,  # workspace.budget_ceiling_monthly
        "within_experiment_ceiling": bool,  # workspace.budget_ceiling_per_experiment
    },
    "mode": str,
    "integration": str,
    "proposed_amount": float,
}
```

`allowed` is `True` only when **every** checklist item is `True`. A missing
piece — no credentials, live mode off, over budget — blocks the action and
returns a clear reason; it never throws an exception into the caller's
code path (matching this repo's "never raise in the money path" principle).

**The checklist is always journaled**, regardless of outcome — every call
appends a `shadow_live_mode_checklist` event to `backend.orchestration.
event_store`, the same always-journal invariant `organic_gate.py` and
`tiktok_ads.py` already follow. This means even a blocked attempt leaves a
durable audit trail of what was requested and why it didn't proceed.

## Composition with `services.ecommerce_operator.launch_guard`

The e-commerce operator's launch guard (`evaluate_launch_readiness`) is a
second, business-logic-specific checklist layered on top:

- **Always checked** (dry-run or live): does the experiment carry product
  validation, margin analysis, supplier assumptions, a budget ceiling, kill
  criteria, and an attribution method? These are prerequisites for a
  *trustworthy analysis*, not spend-safety per se — a dry-run test missing
  them is still "not ready," even though nothing is at financial risk yet.
- **Only checked when `live_action_requested=True`**: `LiveModeChecklist`
  above. A dry-run test is never blocked by "workspace isn't in live mode"
  — that check only applies once you actually ask to go live.

```python
readiness = evaluate_launch_readiness(
    envelope, workspace=ws, live_action_requested=True,
    integration="shopify", proposed_amount=50.0,
)
if not readiness.ready:
    print(readiness.blocked_reasons)
```

## Composition with `backend.risk.gate`

Real ad-spend scaling (`services.ecommerce_operator.scale_decision.
make_kill_scale_decision`, when deciding `scale_approved` vs.
`scale_cautiously`) calls the pre-existing `backend.risk.gate.check_spend()`
— the *same* real-money choke point `backend/integrations/tiktok_ads.py`
and `meta_ads_client.py` already call before any live campaign
create/scale. This is read-only from the service-module side: nothing in
`services/` ever calls `record_spend()` — that only happens once a real
platform call actually succeeds, which stays the integration layer's job,
not the service module's.

## What "live" actually means today, module by module

| Module | Ever mutates a real external system? |
|---|---|
| `product_research`, `unit_economics`, `creative_growth`, `customer_intelligence`, `digital_products` | No — read-only analysis, always. `dry_run`/`status` fields reflect the workspace's posture but nothing here can spend or send anything regardless. |
| `ecommerce_operator` | No execution itself — `evaluate_launch_readiness`/`make_kill_scale_decision` produce a decision and a readiness verdict; a human or a separate, already-existing, already dry-run-gated call (`backend/integrations/*`, `backend/creation/store_builder.py`) executes it. |
| `sales_automation` | No — simulation-only, no real messaging adapter exists (see `docs/SALES_AUTOMATION_MODULE.md`). |

**In short: nothing built in this modularization effort can spend real
money or contact a real customer on its own.** Every module either
produces read-only analysis, or a decision/readiness verdict that a
separate, pre-existing, already-gated integration must still execute.
