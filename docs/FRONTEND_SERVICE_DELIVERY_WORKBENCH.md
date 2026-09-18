# Frontend service-delivery workbench

Updated: 2026-09-18  
Lane: PR #264 (`cursor/service-delivery-workbench-f3a6`)  
Status: draft operator review surface. Not commercially validated.

## Contract consumed

Single adapter: `frontend/src/features/service-delivery-workbench/lib/adaptServiceProjection.ts`.

Accepted **inputs**:

| Input version | Source |
|---|---|
| `service-engagement-projection-v1` | Existing #264 workbench projection |
| `service-delivery-plane-v1` | PR #261 `ServiceDeliveryPlaneReport` / `ClientEngagement.to_dict()` copies, including `package_id` aliases |

Output schema is always `service-engagement-projection-v1`; endpoint status is `available_read_only` only for a validated sanitized artifact, otherwise `unavailable`.

Canonical probe: `GET /api/service-delivery/workbench` via `#213` `frontend/src/lib/apiBase.ts` (`resolveApiBaseUrl` + `joinApiPath`). The backend route is GET-only and reads only an operator-configured artifact beneath `artifacts/`; there is no second API client and no frontend `ServiceEconomics` calculator.

HTTP route: available read-only when `MARKETOS_SERVICE_DELIVERY_PROJECTION` points to a safe artifact; otherwise the response is explicitly `unavailable`. Read-only availability never means live validation, client approval, or mutation authority.

## State taxonomy

CompanyOS / #261 lifecycle (plus frontend `unavailable`):

`intake` → `screening` → `data_inadequate` | `eligible` → `scoped` → `evidence_collection` → `analysis` → `draft_ready` → `client_review` → `revision_requested` → `approved` → `delivered` → `renewal_candidate` | `upsell_candidate`, plus `paused` / `cancelled` / `rejected` / `unavailable`.

Workbench **surface** states: `loading`, `empty`, `blocked`, `unavailable`, `stale`, `partial`. `success` is not emitted while the live endpoint is down.

`data_inadequate` is a hard blocker: client-safe export is rejected and lists exact missing client inputs.

## Evidence limitations

- Fixture / manual_import / simulated / assumption classes are screening copies.
- Evidence class is never upgraded (including blocking `live` → `live_validated`).
- Economics `fee` / `contribution` are backend-provided display labels (`frontend_calculates: false`).
- Draft-ready is not commercial validation. Higgsfield skills remain draft/unavailable metadata only.

## Operator usage

Route: `/operator/services` (read-only).

1. Filter without re-ranking (source order preserved).
2. Keyboard: ArrowUp/Down, Home/End, Enter/Space select; skip link to pipeline.
3. Inspect intake, data-quality blockers, package/scope, evidence, assumptions, economics copies, acceptance criteria, draft report preview, client review/revision/approval/delivery/renewal/upsell callouts, export preview.
4. Export is client-safe or rejected with the reason and missing fields. Internal prompts, formulas, heuristics, credentials, paths, raw HTML, and cross-client keys are omitted/rejected.

## Tests and browser/E2E

- `frontend/tests/service-delivery-workbench*.test.mjs` (adapter, export, a11y source contracts, 1/10/100/500 bench).
- Browser E2E: **not run** in this lane (no mutating journey; source-contract coverage for keyboard/live regions/tables).
- CoderOS: unavailable on this worktree.

## Overlap

Does not implement `evaluation/companyos/service_delivery.py` (#261). Does not edit first-phase cockpit files (#230). `apiBase.ts` remains the #213-shaped helper; workbench consumes it rather than `api.ts` POST helpers.
