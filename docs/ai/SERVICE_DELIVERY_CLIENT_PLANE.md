# Service Delivery Client Plane

Schema: `MarketOS.ServiceDelivery.v1`

This plane lets MarketOS deliver four paid consulting packages as planning
records. It does not invoice, collect payment, message clients, or run live
ads. It does not own a second catalog.

## Authorities consumed

- `evaluation.companyos.service_catalog` — package identity, price bands, inputs, deliverables
- `evaluation.companyos.finance.build_finance_plan` — catalog margin planner
- `evaluation.trustos.client_workspace_isolation` — export boundary and leakage checks

Not modified: financial kernel, Approval Ledger, Resource Execution Governor,
TrustOS core, AI-chat packets, deployment files, frontend cockpit.

## Priority packages (aliases over the catalog)

| Alias | Catalog package |
| --- | --- |
| product-validation-sprint | product-opportunity-report |
| unit-economics-diagnostic | finance-planning-dashboard |
| launch-draft-pack | launch-draft-pack |
| managed-acquisition-cro | managed-marketing-cro |

Prices remain catalog planning bands. Overlay fields (labor, tooling,
contractor, reserve) are labeled `planning_assumption` and are never silently
treated as invoices. USD, MXN, and CAD are never converted.

## Lifecycle

draft → intake_requested → intake_received → data_quality_assessed →
evidence_collection → analysis_in_progress → internal_review → client_review →
delivered → revision_requested → accepted → renewal_or_upsell

Terminal / hold states: blocked, rejected, cancelled, data_inadequate.

Insufficient, blocked, or unavailable intake cannot transition into
`analysis_in_progress` and cannot render a client diagnostic.

## Data-quality gate

Required: orders, revenue, CAC, contribution margin, period start/end, channel,
returns/refunds, ad spend, offer identity.

States: adequate, partial, stale, conflicting, insufficient, blocked, unavailable.

## Economics (planning Decimal arithmetic)

```
incremental_contribution = ad_spend × contribution_margin × (ROAS_after − ROAS_before) − service_fee
orders_required_to_recover_fee = service_fee / (CAC_before − CAC_after)
```

Value flags: client break-even, client attractive value, minimum acceptable
value. All labeled `planning_assumption`.

## Client-safe export

`evaluation.companyos.service_delivery_export` projects the four packages.
Exports are workspace-scoped planning records. Artifact IDs are
workspace+engagement+package digests and cannot be forged. Cross-workspace
reads fail closed. Internal prompts, formulas, heuristics, credentials, raw
payloads, and filesystem paths are stripped.
