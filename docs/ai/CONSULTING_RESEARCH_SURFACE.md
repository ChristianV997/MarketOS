# Consulting research surface

Canonical feature path: `frontend/src/features/consulting-research-surface/`.

This integration keeps one UI. Draft #314 supplied the state machine (loading, error, empty, blocked, stale, partial) and explicit conflict and missing-evidence rows. Draft #305's parallel `consulting-research-workbench` is not copied, so the two drafts do not both land. Leave #305 and #314 open until a merger closes them. Shell, Sidebar, and unrelated Phase 1 / Approval Ledger lanes stay untouched from this docs path unless a route mount is explicitly owned here.

Every adapted model sets `draft_only: true`, `live_validated: false`, and `launch_authorized: false`. Fixture evidence cannot compose to success.

## Mount

Route (Shell child in `frontend/src/main.tsx` only):

```tsx
{ path: "/operator/consulting-research", element: <ConsultingResearchSurfacePage /> }
```

Import `ConsultingResearchSurfacePage` from `frontend/src/features/consulting-research-surface/index.ts`. Do not edit `Shell.tsx` or `Sidebar.tsx` from this feature.

## Operator journey

1. Open `/operator/consulting-research`. The default mode is the **live authenticated boundary**.
2. Submit candidate/product query, category, geography, language, and buyer context. The client uses `frontend/src/lib/apiBase.ts` and `credentials: "same-origin"`. It does **not** accept a caller-supplied workspace id as authority and does not store bearer tokens.
3. Until a verified session provider and gated report route exist, the live panel stays `auth_required` / `unavailable` (see contract below). Failed live requests **never** silently fall back to fixture JSON.
4. Optionally enable **Demo/fixture — not live evidence** for local development. That path can load a fixture packet or a local JSON file (`market-research-service-v1` / `consulting-research-surface-v1`) in memory only (512 KiB cap). Reset demo returns to the fixture; Reset live clears the live request without entering demo mode.
5. Inspect sections, conflicts, missing fields, blockers, per-source status, and the client-safe export preview. No second scorer or economics authority is introduced in the UI.

## Live contract handoff (proposed)

| Item | Value |
|---|---|
| Endpoint | `POST /api/consulting-research/report` (`LIVE_RESEARCH_REPORT_ENDPOINT`) |
| Request version | `consulting-live-research-request-v1` |
| Response shapes | `market-research-service-v1` or `consulting-research-surface-v1` |
| Auth | Principal-gated; workspace from verified session (`backend/identity/http.py`) |
| Status today | **Not implemented** on main — frontend reports `unavailable` / `auth_required` |

Backend dependency: mount the route over `services.market_research.build_market_research_report` (or an equivalent CRS projection), wire `get_token_verifier` + `get_workspace_repository`, reject client `workspace_id` authority.

## Evidence

Classes are `observed`, `manual`, `fixture`, `derived`, `assumed`, and `unavailable`. `live` and `live_validated` become `unavailable`. Fixture packets compose to `blocked`, `stale`, `partial`, `empty`, or `unavailable`, never `success`. `launchAuthorized` is always false. Missing fields and conflict notes are listed from the packet. Export omits prompts, formulas, source code, credentials, raw payloads, hidden heuristics, and cross-client data.

## Safety boundaries

- No upload endpoint, localStorage/sessionStorage persistence of reports or tokens, or provider credentials in the browser.
- No approve / spend / publish / launch controls.
- Demo/fixture is explicit opt-in only and never substitutes for a failed live request.
- Canonical offline producer remains `services.market_research` / `scripts/market_research_report.py` until the live route exists.
