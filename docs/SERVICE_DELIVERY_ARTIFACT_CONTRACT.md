# Service Delivery Artifact — Stable Contract

`evaluation.companyos.service_delivery_artifact` is the single, deterministic,
client-safe projection that any future consumer (in particular PR #264's
frontend workbench) should read instead of reaching into
`ClientEngagement`/`ServiceEconomics`/`ClientDataQualityAssessment`
individually. **Frontend files are out of scope for this lane** — this
document only defines the backend contract PR #264 will consume later.

## What it is, and is not

It is a **projection**, built on demand from existing authorities:

| Concern | Authority | Role here |
|---|---|---|
| Identity, lifecycle, data-quality | `evaluation.companyos.service_delivery` | Reused verbatim; never re-derived. |
| Money/economics | `backend.economics.kernel` (`ServiceEconomics`) | Reused verbatim via `evaluate_engagement_economics()`; never re-derived. |
| Deliverable container | `backend.deliverables.package.DeliverablePackage` | Reused verbatim; the artifact reads its already-redacted `derived_values` and `metadata.leakage_findings`, it does not redact independently. |
| Export boundary | `evaluation.trustos.client_workspace_isolation.check_workspace_leakage` | Reused transitively through `build_client_service_deliverable()`; this module adds no second boundary. |

It is **not** a second service catalog, price book, financial engine, export
boundary, or client database. `build_service_delivery_artifact()` is a pure
function: given an engagement, package, economics result, data-quality
assessment, and deliverable, it returns one `ServiceDeliveryArtifact` value.
It stores nothing itself.

## Compatibility with PR #247

As of this writing, PR #247's research-to-decision projection module does
not exist anywhere in this branch's dependency tree (confirmed: not
importable). No schema was copied from it and no score was recalculated
from it. **If #247 lands with a compatible evidence-classification or
projection shape, map this artifact's fields to it by reference** (e.g. a
shared `EvidenceClassification` type both modules import), not by copying
its logic or duplicating its scoring. Until then, `classify_evidence_ref()`
here is this module's own presentation mapping over the kernel's
`EvidenceRef.evidence_state` — safe to keep as the fallback if #247 never
lands, or to delegate to if it does.

## Field reference

`ServiceDeliveryArtifact.to_dict()` (schema `MarketOS.ServiceDeliveryArtifact.v1`):

| Field | Meaning |
|---|---|
| `artifact_id` | Deterministic hash of `(engagement_id, package_id, package_version)`. **Stable across rebuilds of the same engagement+package** — idempotent creation. |
| `replay_hash` | Deterministic hash of the full content payload. **Changes whenever the engagement's lifecycle state, evidence, or economics change** — use this, not `artifact_id`, to detect a genuine revision vs. a duplicate replay (see `is_duplicate_replay()`). |
| `workspace_id`, `engagement_id`, `package_id`, `package_version` | Identity. `package_version` bumps invalidate `artifact_id` verification (`verify_artifact_id()`), which is the package/version-compatibility guard. |
| `lifecycle_state`, `data_quality_state` | Read directly from the engagement / data-quality assessment. |
| `evidence_references`, `evidence_classifications` | One classification per evidence reference, from `classify_evidence_ref()` — see the classification table below. |
| `observed_values`, `derived_values`, `assumptions`, `missing_evidence`, `blockers` | The deliverable's own already-redacted content plus the data-quality gate's own missing/blocking reasons. |
| `planned_deliverables`, `acceptance_criteria` | From the package catalog, unchanged. |
| `planned_hours`, `consumed_hours`, `tooling_cost`, `pass_through_cost`, `fee`, `currency` | From the engagement/package; currency is always internally consistent across all three Money fields (never mixed). |
| `contribution_reference` | `None` when `economics` was never computed (e.g. `data_inadequate`); otherwise a reference into the kernel's own `ServiceEconomics` fields — no formula recomputed. |
| `client_value_classification` | From `classify_client_value()`, unchanged. |
| `approval_state`, `delivery_state`, `renewal_state` | Read directly from the engagement. |
| `revision_history` | Ordered, exactly matching `engagement.history` — never re-sorted. |
| `next_human_action` | A short, deterministic string keyed by `lifecycle_state`; always present, even when blocked. |
| `safe_export_status` | `"client_safe"` or `"redacted"`, from the deliverable's own `metadata.leakage_findings` count. |
| `read_only` / `network_calls` / `mutated` | Always `True` / `False` / `False` — this is an offline planning record. |

## Evidence classification vocabulary

`planning_assumption`, `fixture`, `manual_import`, `derived`,
`supplier_claimed`, `supplier_documented`, `public_observed`,
`sample_verified`, `live_validated`, `unavailable`.

Mapped from the kernel's own `EVIDENCE_STATES`:

| Kernel `evidence_state` | Artifact classification |
|---|---|
| `assumed` | `planning_assumption` |
| `fixture` | `fixture` |
| `simulated` | `manual_import` |
| `derived` | `derived` |
| `observed` | `public_observed` |
| `verified` | `sample_verified` |
| `live_readonly` | `live_validated` |
| `unknown`, `missing`, `stale`, `rejected` | `unavailable` |

A caller-supplied `supplier_tier` (`"claimed"` / `"documented"`) only ever
applies on top of a **non-live-adjacent** base classification — it can
never upgrade `live_readonly`/`verified` evidence, and it can never be used
to promote fixture/manual/simulated evidence into `live_validated`. This is
directly regression-tested
(`test_supplier_tier_cannot_launder_fixture_evidence_into_live_validated`,
`test_non_live_evidence_states_never_classify_as_live_validated`).

## Compatibility rules for future changes to this module

1. Never add a field that duplicates a value already owned by
   `ClientEngagement`, `ServicePackage`, or `ServiceEconomics` — reference
   it, don't copy it.
2. Never let `build_service_delivery_artifact()` write to disk, a registry,
   or an event log itself — it stays a pure projection function. If a
   caller wants persistence, it already has `DeliverableRegistry`
   (via the `deliverable` argument) for that.
3. `artifact_id` must remain a function of identity only
   (`engagement_id`, `package_id`, `package_version`); `replay_hash` must
   remain a function of full content. Do not conflate the two.
4. Any new evidence classification must be added to
   `ARTIFACT_EVIDENCE_CLASSIFICATIONS` and to the kernel-state mapping
   table above — never inferred ad hoc at a call site.
