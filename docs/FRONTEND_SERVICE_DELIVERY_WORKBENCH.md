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
| `service-delivery-plane-v1` | PR #275 producer (`evaluation.companyos.service_delivery_projection`) and #261 `ClientEngagement.to_dict()` copies, including `package_id` aliases |

Output schema is always `service-engagement-projection-v1`; endpoint status is `available_read_only` only for a validated sanitized artifact, otherwise `unavailable`.

Canonical probe: `GET /api/service-delivery/workbench` via `#213` `frontend/src/lib/apiBase.ts` (`resolveApiBaseUrl` + `joinApiPath`). The backend route (#271) is GET-only and reads only an operator-configured artifact beneath `artifacts/`. This frontend lane consumes that envelope; it does not add an endpoint, economics engine, second API client, or new projection schema.

HTTP route: available read-only when `MARKETOS_SERVICE_DELIVERY_PROJECTION` points to a safe #275 artifact; otherwise the response is explicitly `unavailable`. Read-only availability never means live validation, client approval, or mutation authority. Envelope `availability` of `fixture` / `manual_import` / `partial` never promotes evidence to `live_validated`.

## State taxonomy

CompanyOS / #261 lifecycle (plus frontend `unavailable`):

`intake` → `screening` → `data_inadequate` | `eligible` → `scoped` → `evidence_collection` → `analysis` → `draft_ready` → `client_review` → `revision_requested` → `approved` → `delivered` → `renewal_candidate` | `upsell_candidate`, plus `paused` / `cancelled` / `rejected` / `unavailable`.

Workbench **surface** states: `loading`, `empty`, `blocked`, `unavailable`, `stale`, `partial`. `success` is never emitted when the endpoint is unavailable or the envelope is fixture/manual/partial.

Selected lifecycle states are displayed as copies: `data_inadequate`, `draft_ready`, `client_review`, `revision_requested`, `approved`, `delivered`, `cancelled`, `rejected` (plus the rest of the CompanyOS vocabulary). They do not grant mutation authority.

Compose bounds the filtered list at 500 rows without re-ranking.

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

- `frontend/tests/service-delivery-workbench*.test.mjs`
- `frontend/tests/service-workbench-producer-acceptance.test.mjs` (#275 envelope consume)
- `frontend/tests/readonly-cockpit-browser-acceptance.test.mjs`
- Browser E2E: **unavailable** unless a real harness executes.

## Overlap

Does not implement `evaluation/companyos/service_delivery.py` (#261) or `evaluation/companyos/service_delivery_projection.py` (#275). Does not edit `api/routes/service_delivery_workbench.py` or `backend/api.py` (#271). `apiBase.ts` remains the #213-shaped helper.

#271 GET envelopes (`service_delivery_projection_not_configured`, `available_read_only` + `read_only_artifact_projection`, `packages[]` engagement rows, 429 `rate_limited`) are adapted by the same consumer. #261 `Money.to_dict()` `amount` copies become display labels; they are never recomputed. Renewal/upsell metadata (`renewal_state`, `approval_state`, `delivery_state`) are copied for display only.
