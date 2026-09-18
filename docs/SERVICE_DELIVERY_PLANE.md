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

`ClientEngagement` moves through a deterministic, forward-only state graph
(v3: reconciled against lane `SERVICE-DELIVERY-CLIENT-PLANE-V3-RECONCILIATION`'s
required vocabulary):

```
intake -> screening -> eligible -> scoped -> evidence_collection -> analysis
       -> draft_ready -> client_review -> approved -> delivered
                                        \-> revision_requested -> analysis
screening/evidence_collection/analysis -> data_inadequate -> screening | rejected | cancelled
delivered -> renewal_candidate | upsell_candidate -> intake (a fresh engagement)
any non-terminal state -> paused -> (resumes at any earlier non-terminal state) | cancelled
```

`data_inadequate` is a first-class, actionable lifecycle state, not a
warning flag on the side: it is reachable from every stage that depends on
client-supplied business data, and always has a real way forward (resume
`screening` once more evidence arrives) or a real way out (`rejected` /
`cancelled`) — it is never a dead end and never silently downgrades to an
optimistic result.

`create_engagement()` requires a `client_service` workspace, rejects a
secret-shaped `scope` or any secret-shaped string in `intake_data` (matching
common token prefixes such as `sk-`, `ghp_`, `-----BEGIN`), and produces a
deterministic `engagement_id` (SHA-256 of client/workspace/package/timestamp
— stable for the same inputs, distinct across clients or workspaces).
`transition_engagement()` rejects any transition not in the graph.
`verify_engagement_id()` recomputes that hash from an engagement's own
fields and flags any record whose identity fields were mutated after
construction (e.g. relabeling one client's engagement into another
client's workspace) even though every individual field still looks
well-formed.

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
gate classifies the **client's own supplied business data** across 11
required fields: client identity, product/offer identity, date range,
revenue, orders, ad spend, CAC/ROAS inputs, product and fulfillment costs,
shipping, returns/refunds, and payment/platform fees — before any
diagnostic is produced.

States: `adequate`, `partial`, `stale`, `conflicting`, `insufficient`,
`blocked`, `unavailable`. A client missing, or holding stale/conflicting
evidence for, any required field is marked `data_inadequate = True` and
never receives a computed diagnostic — `build_client_service_deliverable()`
returns a `blocked` package naming the exact missing evidence instead, and
the engagement lifecycle itself moves to the `data_inadequate` state (see
section B) rather than silently continuing. Unknown values stay unknown:
a missing field is recorded in `missing_fields`, never defaulted to zero
revenue, zero orders, or any other numeric placeholder.

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

## V3 reconciliation with PR #260

Lane `SERVICE-DELIVERY-CLIENT-PLANE-V3-RECONCILIATION` asked this PR (#261)
to absorb the stronger lifecycle/data-quality/workspace-separation design
of a parallel PR #260, while keeping this PR's correct canonical-kernel
import (#260 reimplements its own local `ServiceEconomics`-shaped
calculation instead of importing `backend.economics.kernel`, which this
PR must not copy).

**#260's core module could not actually be read or run**:
`evaluation/companyos/service_delivery_plane.py` as committed on
`grok/marketos-service-delivery-client-plane-v2` is a single 746-byte line
with literal `\n` escape sequences instead of real newlines — not valid,
importable Python (confirmed: `wc -l` reports 0 lines). #260's own PR body
acknowledges this ("copy the exclusive files from artifacts if the GitHub
blob... is not yet the full v4 module") and points at a local
`artifacts/marketos-service-delivery-plane/` directory that does not exist
anywhere in the pushed branch. **#260 was not modified** (out of scope per
this mission), and this PR does not depend on it.

What #260's intended design *could* be recovered from its (intact) test
file `tests/evaluation/test_service_delivery_plane.py` and its working
`service_delivery_export.py`, and was adopted here on merit, reimplemented
against the canonical kernel rather than copied:

- the more granular lifecycle vocabulary (`intake`/`screening`/`eligible`/
  `scoped`/`draft_ready`/`approved`/`renewal_candidate`/`upsell_candidate`/
  `paused`/`cancelled`), replacing this PR's earlier, coarser one;
- `data_inadequate` promoted from a boolean flag to a first-class lifecycle
  state;
- a wider (11-field) client business-data-quality checklist;
- rejecting secret-shaped strings in `scope`/`intake_data` at intake time
  (defense-in-depth alongside the existing output-side leakage check);
- `verify_engagement_id()`, an explicit forgery/tamper check.

Also fixed per this mission's explicit instruction: `evaluate_engagement_economics()`'s
`contractor_cost` parameter used `contractor_cost or Money.zero(...)` to
supply a default. `Money` defines no `__bool__`/`__len__`, so an explicit
zero-amount `Money` is still Python-truthy and this did not actually drop
real inputs today — but the pattern was fragile and inconsistent with the
`is not None` checks used for every other optional cost parameter, so it
is now explicit (see `test_explicit_zero_contractor_cost_is_a_valid_amount_not_a_missing_default`).

## What this module does not do

- It does not send client messages, collect payment, place supplier orders,
  or publish anything.
- It does not create a CRM, billing processor, or public SaaS identity
  system.
- It does not persist raw client PII beyond the `intake_data` mapping the
  caller supplies; no filesystem paths, credentials, or model traces appear
  in any client-facing output.
