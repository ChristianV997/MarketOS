# Service Delivery Plane

`evaluation.companyos.service_delivery` implements the reusable
client-engagement layer that lets MarketOS deliver paid ecommerce research,
validation, economics, launch-planning, and acquisition-diagnostic work to
external clients while keeping internal ecommerce operations and client data
strictly separated.

It is offline planning only. It never performs outreach, advertising,
customer messaging, payment collection, supplier ordering, storefront
publishing, or any live provider action.

## Canonical authorities reused (not duplicated)

| Concern | Canonical authority | This module's role |
|---|---|---|
| Service pricing/catalog identity | `evaluation.companyos.service_catalog.ServicePackage` | `ClientFacingServicePackage` is a read-only compatibility layer adding client-delivery metadata; every price figure delegates to the catalog. |
| Money arithmetic | `backend.economics.kernel` (`Money`, `ServiceEconomics`, `calculate_service_economics`, `incremental_contribution`, `orders_required_to_recover_fee`) | `evaluate_engagement_economics()` is a thin, currency-checked pass-through. No formula is reimplemented. |
| Tenant/workspace identity | `backend.workspaces.client_workspace.ClientWorkspace` | Engagements are keyed by `ClientWorkspace.workspace_id`; only `workspace_type == "client_service"` workspaces may hold engagements. |
| Deliverable container | `backend.deliverables.package.DeliverablePackage` / `DeliverableSection`, registered in the existing `backend.deliverables.registry.DeliverableRegistry` | Client deliverables use `package_type` values prefixed `client_` (e.g. `client_product_validation_sprint`) so they share one registry with every other deliverable, distinguished by type rather than a second registry. |
| Internal-to-client export boundary | `evaluation.trustos.client_workspace_isolation.check_workspace_leakage` | Every deliverable payload is checked before being considered client-safe; any flagged value is redacted, never silently forwarded. |

No second service catalog, money engine, workspace/export boundary, CRM,
billing processor, payment mutation path, or report authority is created.

## A. Canonical service packages

`default_service_delivery_packages()` returns the four packages below,
identified by the catalog's existing `canonical_package_id`/`canonical_name`
aliases (already present in `service_catalog.py`):

1. **Product Validation Sprint** (`product-validation-sprint`)
2. **Unit Economics + CAC/ROAS Diagnostic** (`unit-economics-cac-roas-diagnostic`)
3. **Launch Draft Pack** (`launch-draft-pack`)
4. **Managed Acquisition/CRO** (`managed-acquisition-cro`)

Each `ClientFacingServicePackage.to_dict()` exposes: package ID, name,
description, currency, price range, billing model, estimated delivery
hours, estimated labor cost, tooling cost, optional pass-through cost,
refund/revision reserve, required client inputs, client eligibility,
deliverables, acceptance criteria, expected outcome, scope exclusions,
next-step relationship, price evidence state, and an explicit
`price_evidence_classification` of `planning_assumption` or
`validated_price` (all four ship as `planning_assumption` — no package
price here is claimed as market-validated).

Currency is never silently converted: package cost defaults are only used
when they already match the caller's fee currency; a mismatch raises
`CurrencyMismatchError` immediately (see `test_currencies_are_never_silently_converted_*`
in `tests/test_service_delivery.py`).

## B. Client engagement lifecycle

`ClientEngagement` moves through a deterministic, forward-only state graph:

```
draft -> intake_requested -> intake_received -> data_quality_assessed
      -> evidence_collection -> analysis_in_progress -> internal_review
      -> client_review -> delivered -> accepted -> renewal_or_upsell
                        \-> revision_requested -> analysis_in_progress
any state -> blocked -> (resumes at the next forward state) | rejected
```

`create_engagement()` requires a `client_service` workspace and produces a
deterministic `engagement_id` (SHA-256 of client/workspace/package/timestamp
— stable for the same inputs, distinct across clients or workspaces).
`transition_engagement()` rejects any transition not in the graph.

`ClientEngagement.approval_state` is a lifecycle field distinct from the
CompanyOS **Approval Ledger** (`evaluation.companyos.approval_ledger`): it
tracks internal client sign-off, not external side-effecting actions. Any
future action derived from an accepted engagement that would touch a live
provider, spend, or customer contact must go through the Approval Ledger
and Resource Execution Governor like any other execution request — this
module does not and must not short-circuit that gate.

## C. Client business-data quality gate

`assess_client_data_quality()` is a **new, distinct** gate from
`evaluation.contracts.DataQuality` (which classifies *evidence provenance*
for product/campaign signals, e.g. fixture vs. live vs. attributed). This
gate classifies the **client's own supplied business data** — their orders,
revenue, CAC, contribution margin, channel data, and period definitions —
before any diagnostic is produced.

States: `adequate`, `partial`, `stale`, `conflicting`, `insufficient`,
`blocked`, `unavailable`. A client missing, or holding stale/conflicting
evidence for, any of the six required fields is marked
`data_inadequate = True` and never receives a computed diagnostic —
`build_client_service_deliverable()` returns a `blocked` package naming the
exact missing evidence instead.

## D. Service economics

`evaluate_engagement_economics()` calls
`backend.economics.kernel.calculate_service_economics()` directly, combining
`labor_cost + contractor_cost` into the kernel's `delivery_cost` parameter
(the kernel does not have a separate contractor-cost field, so this module
adds contractor cost at the call site rather than extending the kernel for a
straightforward sum). The kernel already implements, unchanged:

- `incremental_contribution = ad_spend × contribution_margin × (ROAS_after − ROAS_before) − service_fee`
- `orders_required_to_recover_fee = service_fee / (CAC_before − CAC_after)`
- contribution, contribution margin, contribution per delivery hour, capacity
  utilization, maximum simultaneous clients, required client count for a
  target monthly contribution, and client value multiple.

`classify_client_value()` distinguishes `below_break_even`, `break_even`,
`below_minimum_acceptable`, `acceptable`, and `attractive` from the kernel's
`client_value_multiple` and `minimum_acceptable_value_multiple` — the
minimum acceptable value MarketOS must create is never conflated with an
"attractive" outcome.

## E. Deliverable generation

`build_client_service_deliverable()` builds one `DeliverablePackage` per
engagement with a `metadata` payload carrying: observed facts, assumptions,
derived values, missing evidence, confidence (the kernel's own
`evidence_state`), limitations, recommendation, next action, evidence
references, currency, and source timestamps. The payload is checked with
`check_workspace_leakage()` before being finalized; any flagged
credential-shaped or cross-client-shaped value is redacted, matching the
existing pattern used in `evaluation/commerce/product_validation_report.py`.

## F. Workspace isolation

- `get_client_engagement_for_workspace()` returns `None` for any
  `workspace_id` mismatch, even for a valid `engagement_id`.
- `list_client_deliverables_for_workspace()` requires an explicit
  `workspace_id` and delegates to `DeliverableRegistry.list_packages()`'s
  own filter — it never lists unscoped.
- Engagement and deliverable IDs are deterministic hashes of
  `(client_id, workspace_id, package_id, timestamp)`; two different clients
  or workspaces never collide (see `test_artifact_ids_cannot_be_forged_across_clients`).

## What this module does not do

- It does not send client messages, collect payment, place supplier orders,
  or publish anything.
- It does not create a CRM, billing processor, or public SaaS identity
  system.
- It does not persist raw client PII beyond the `intake_data` mapping the
  caller supplies; no filesystem paths, credentials, or model traces appear
  in any client-facing output.
