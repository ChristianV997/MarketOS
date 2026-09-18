# Service Delivery Client Economics Plane

Schema: `MarketOS.ServiceDelivery.v4`

This plane lets the operator sell and deliver four ecommerce consulting
packages as deterministic planning records. It is not a CRM, billing
system, workflow engine, or second catalog. It does not invoice, collect
payment, message clients, publish storefronts, or run live ads.

## Authorities consumed (not duplicated)

- `evaluation.companyos.service_catalog` — package identity and USD planning bands
- `evaluation.companyos.finance.build_finance_plan` — catalog margin planner
- `evaluation.trustos.client_workspace_isolation` — export boundary
- `evaluation.companyos.resource_execution_governor` — live-action default-deny

Not modified: `#248`/`#250` financial kernel, Approval Ledger, AI-chat
packets, deployment files, frontend cockpit, payment or storefront paths.

`backend.economics.kernel` is **unavailable on origin/main**
(`df59a060`). Service contribution arithmetic in this plane is a
planning-assumption Decimal helper labeled `planning_assumption`. It must
be replaced by a pass-through to the kernel after `#248` merges. No
second money authority is claimed.

## Priority packages (aliases over the catalog)

| Alias | Catalog package | Deliverable kind |
| --- | --- | --- |
| product-validation-sprint | product-opportunity-report | product_validation_report |
| unit-economics-diagnostic | finance-planning-dashboard | economics_diagnostic |
| launch-draft-pack | launch-draft-pack | launch_draft |
| managed-acquisition-cro | managed-marketing-cro | managed_acquisition_experiment_plan |

Catalog bands stay USD. `bind_explicit_currency` keeps MXN/USD/CAD
explicit. A mismatch is `separated_no_fx`: catalog `price_min`/`price_max`
are not reused as the fee, and no FX conversion occurs.

## Lifecycle

`intake → data_quality_review → scoped → approved → in_delivery →
internal_review → client_review → delivered → revision_window → closed →
renewal_or_upsell`

Gate / terminal states: `needs_evidence`, `hold`, `reject`, `cancelled`,
`data_inadequate`.

Each transition names an approver (`operator`, `delivery_owner`,
`client_approver`, `sales_owner`). No live action follows a transition.
Aliases from the v1 state names still normalize into this graph.

## Data-quality and eligibility

Required intake: orders, revenue, CAC, contribution margin, period
start/end, channel, returns/refunds, ad spend, offer identity.

Quality states: adequate, partial, stale, conflicting, insufficient,
blocked, unavailable.

Eligibility reasons produce `needs_evidence`, `hold`, or `reject` — never
an optimistic recommendation:

- insufficient data
- unreliable revenue
- missing CAC
- missing contribution margin
- missing fulfillment evidence
- missing authority to change offers
- unsupported market
- unsupported currency
- unresolved compliance
- client cannot economically justify the fee

## Economics (planning Decimal, evidence_state=planning_assumption)

```
contribution_profit = fee − (labor + tooling + contractor + reserve)
incremental_contribution = ad_spend × contribution_margin × (ROAS_after − ROAS_before) − fee
orders_required_to_recover_fee = fee / (CAC_before − CAC_after)
```

Also computed: contribution margin, contribution per hour, capacity,
max simultaneous clients, required clients for a monthly contribution
target, client value multiple, 1.25x–1.50x value-creation flags.

## Client-safe export

`evaluation.companyos.service_delivery_export` projects the four packages
through TrustOS isolation. Artifact IDs are workspace+engagement+package
digests. Cross-workspace reads fail closed. Internal prompts, formulas,
heuristics, credentials, raw payloads, and filesystem paths are stripped.
Internal ecommerce workspaces cannot enter the client plane.

## Dry-run CLI

`scripts/run_service_delivery_plane.py` writes offline planning records
only.
