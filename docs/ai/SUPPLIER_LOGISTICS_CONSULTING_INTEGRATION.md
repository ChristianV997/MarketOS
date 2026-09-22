# Supplier & Logistics Consulting Integration

`services/supplier_logistics_consulting_integration/` connects
`services.supplier_logistics_research`'s evidence reports (PR #308) to the
existing consulting engagement lifecycle, workspace-scoped portfolio
rollup, and TrustOS client-safe export boundary. It composes four existing
authorities; it introduces none of its own.

## What it composes (not duplicates)

| Concept | Source | How it's used here |
|---|---|---|
| Supplier/logistics evidence | `services.supplier_logistics_research.report.build_supplier_logistics_report` | consumed as-is; this module never reconstructs a `SupplierLogisticsReport` |
| Negative controls (secret, HTML, currency, missing money, verified-evidence) | `services.supplier_logistics_research.controls` | re-exported by identity (`services.supplier_logistics_consulting_integration.controls.is_verified is services.supplier_logistics_research.controls.is_verified`, etc.) |
| Consulting engagement lifecycle | `evaluation.companyos.service_delivery` (`ClientEngagement`, `create_engagement`, `transition_engagement`, `verify_engagement_id`, `ENGAGEMENT_STATES`) | `engagement.record_supplier_logistics_evidence` composes one legal transition on this existing state machine |
| Client-facing service packages | `evaluation.companyos.service_delivery.default_service_delivery_packages` / `ClientFacingServicePackage` | the `product-validation-sprint` package (whose own description already names "supplier feasibility" as one of its evidence pillars) is the natural package for a supplier/logistics deliverable |
| Client-safe deliverable container | `backend.deliverables.package.DeliverablePackage` / `DeliverableSection`, `backend.deliverables.registry.DeliverableRegistry` | `export.build_client_safe_deliverable` builds and registers one, exactly as every other client deliverable in this repository does |
| Workspace identity | `backend.workspaces.client_workspace.ClientWorkspace`, `backend.workspaces.registry.WorkspaceRegistry` | every client-facing entrypoint takes an explicit `workspace_id`/`workspace` and re-verifies it against the registry -- see Workspace mismatch below |
| Portfolio rollup | `backend.organization.portfolio_report.PortfolioReport` / `build_portfolio_report` | `portfolio.build_supplier_logistics_portfolio` adapts one or more reports into that function's existing duck-typed input shape (`.report_id`/`.service_name`/`.status`/`.recommendations`/`.next_actions`/`.risk_flags`) |
| TrustOS client-safe export boundary | `evaluation.trustos.client_workspace_isolation` (`export_client_evidence`, `check_workspace_leakage`, `CLIENT_EXPORT_FIELDS`) | `export.export_supplier_logistics_status` calls `export_client_evidence` directly for the narrow, canonical, size-bounded export; `export.build_client_safe_deliverable` calls `check_workspace_leakage` before ever registering a deliverable |

Nothing here re-implements `services.supplier_logistics_research`'s
schemas, controls, or report-building logic, and nothing here creates a
second engagement, deliverable, portfolio, or export authority.

## Architecture note: first `services/**` caller of `evaluation.trustos`/`evaluation.companyos`

At the time of writing, no other file under `services/**` imports
`evaluation.trustos.*` or `evaluation.companyos.*`. `tests/contracts/
test_architecture_boundaries.py`'s `test_services_do_not_own_frontend_or_
low_level_persistence` forbids only `frontend`, `backend.runtime.
replay_store`, `backend.orchestration.event_store`, and `backend.data.
repositories` from `services/**` -- none of those overlap with
`evaluation.*`, so this is architecturally permitted, not a boundary
violation. Following the one existing convention for this exact import
(`evaluation.companyos.service_delivery` and `backend.deployment.
service_delivery_smoke` both import `evaluation.trustos.
client_workspace_isolation` function-locally, to avoid a documented
companyos<->trustos import cycle), every call into `evaluation.trustos` in
this module is also function-local, never a module-level import.

## Module map

- **`controls.py`** -- re-exports `services.supplier_logistics_research.
  controls`' five controls unchanged, and adds the two controls that are
  new at this boundary:
  - `require_workspace_match(claimed_workspace_id, workspace, *, registry)`
    -- re-fetches the workspace from `WorkspaceRegistry` and compares it
    byte-for-byte against the object the caller passed in, exactly
    mirroring `export_client_evidence`'s own identity check. Raises
    `WorkspaceMismatchError`.
  - `reject_cross_client_leakage(payload)` -- runs `payload` through
    `evaluation.trustos.client_workspace_isolation.
    check_workspace_leakage` (the sole leakage authority in this
    repository) and fails closed (raises `CrossClientLeakageError`) on
    any finding, rather than attempting a partial redaction.
- **`engagement.py`** -- `record_supplier_logistics_evidence(engagement,
  report, *, workspace, updated_at, registry)`. Requires the engagement to
  be in the `evidence_collection` lifecycle state (the only state from
  which `evaluation.companyos.service_delivery`'s own transition table
  allows a move to `analysis` or `data_inadequate`), verifies workspace
  match, verifies engagement-identity non-forgery
  (`verify_engagement_id`), verifies the report's quoted-price currency
  matches the engagement's own fee currency, then transitions to
  `analysis` (no blockers, a known offering kind) or `data_inadequate`
  (an unknown offering, or any blocker) carrying the report's evidence
  references, landed-cost scenario assumptions, and blockers onto the
  engagement's own mutable fields.
- **`portfolio.py`** -- `SupplierLogisticsPortfolioEntry.from_report`
  adapts one report into `build_portfolio_report`'s duck-typed shape;
  `build_supplier_logistics_portfolio(workspace_id, reports)` rolls up any
  number of reports (multiple offers for one candidate, or offers across
  candidates) into one `PortfolioReport`.
- **`export.py`** -- two client-safe export shapes:
  - `export_supplier_logistics_status` -- the narrow TrustOS export
    (`workspace_id`/`status`/`blockers`/`evidence_required`/
    `approvals_required`/`next_actions` only), via `export_client_evidence`
    directly.
  - `build_client_safe_deliverable_payload` / `build_client_safe_
    deliverable` -- a richer payload (risk matrix, landed-cost scenario
    ids, evidence-quality summary) checked via `check_workspace_leakage`
    before being placed into a registered `DeliverablePackage`. Optional
    `include_supplier_notes=True` surfaces `FieldEvidence.note` free text
    -- but only after it passes both `controls.reject_unsafe_input`
    (reused from the upstream service) and the TrustOS leakage check.
- **`pipeline.py`** -- `build_consulting_package(...)` composes all three
  into one `ConsultingIntegrationResult` (engagement, deliverable,
  portfolio, status export), with fixed `read_only=True`/
  `network_calls=False`/`mutated=False` invariants enforced by
  `__post_init__`, not just documented.

## Why a supplier note can leak even though the upstream service already has controls

`services.supplier_logistics_research.schemas.FieldEvidence.__post_init__`
only validates that `note` contains no control characters -- it does
**not** screen for secrets, HTML, or cross-client references. That
screening (`services.supplier_logistics_research.controls.
reject_unsafe_input`) is an opt-in utility the upstream service never
calls automatically. `export.collect_supplier_notes` documents this
explicitly, and `build_client_safe_deliverable_payload`'s
`include_supplier_notes` path runs every collected note through
`reject_unsafe_input` before including it -- and `build_client_safe_
deliverable` always additionally runs the whole payload through TrustOS's
`check_workspace_leakage`, which catches a strictly broader marker set
(e.g. `"pricing formula"`, `"heuristic"`, `"strategy"`) than the upstream
service's own narrower secret/HTML/cross-client patterns. A regression
test (`test_controls.py::TestRejectCrossClientLeakage::
test_rejects_an_internal_strategy_marker_not_covered_by_upstream_
controls`) proves this is genuine additional coverage, not a duplicate
check: it confirms the same note passes `reject_unsafe_input` and is then
still rejected by `reject_cross_client_leakage`.

## Safety invariants

Every client-facing entrypoint in this module:
- takes an explicit `workspace`/`workspace_id` and re-verifies it against
  `WorkspaceRegistry` rather than trusting a claimed field on another
  object (workspace-mismatch control);
- never calls a supplier, places an order, books logistics capacity,
  moves money, sends a client message, or authorizes a launch;
- fails closed on any TrustOS leakage finding rather than redacting and
  continuing;
- produces a `ConsultingIntegrationResult` / `SupplierLogisticsReport`
  whose own `read_only=True`/`network_calls=False`/`mutated=False` fields
  are structural invariants (raised on in `__post_init__`), not merely
  documented behavior.

## Limitations and exact provenance

- **Newly written in this change:** `controls.py`, `engagement.py`,
  `portfolio.py`, `export.py`, `pipeline.py`, `__init__.py`, all tests,
  the `multi_offer_candidate_ids.json` fixture, this document.
- **Composed, not duplicated:** every module named in the table above.
- **Not implemented:** this module has no orchestration for walking an
  engagement through its *earlier* lifecycle states (`intake` ->
  `evidence_collection`) -- that machinery already exists in
  `evaluation.companyos.service_delivery` and is reused via
  `create_engagement`/`transition_engagement` directly in tests; this
  module only knows how to attach evidence once an engagement has reached
  `evidence_collection`.
- **Known constraint:** `record_supplier_logistics_evidence` can only be
  called once per engagement while it remains in `evidence_collection`
  (a second call requires a fresh `evidence_collection`-state engagement,
  since `analysis`/`data_inadequate` cannot transition back to
  `evidence_collection` in the existing state machine). Rolling up
  *multiple* offers for one client is instead done at the portfolio layer
  (`portfolio.build_supplier_logistics_portfolio`), which accepts any
  number of reports regardless of which engagement(s) they came from.
- **Currency scope:** the currency-mismatch check in
  `record_supplier_logistics_evidence` compares the report's quoted price
  against the *engagement's* fee currency -- a new check at this
  boundary, distinct from (and layered on top of) the upstream service's
  own offer-vs-lane currency check.
