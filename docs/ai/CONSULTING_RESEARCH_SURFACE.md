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

1. Open `/operator/consulting-research`.
2. Optionally review the fixture demo packet (blocked / non-success).
3. Choose a local JSON file produced by `scripts/market_research_report.py` (`report_version: market-research-service-v1`) or an already-shaped `consulting-research-surface-v1` packet.
4. The browser parses the file in memory only (strict `512 KiB` cap). Invalid, secret-shaped, or mismatched contracts are rejected without echoing payload contents.
5. Market Research reports are reshaped by `mapMarketResearchReport` into the surface model; no second scorer or evidence authority is introduced.
6. Inspect sections, conflicts, missing fields, blockers, and the client-safe export preview. Reset returns to the fixture demo.

## Evidence

Classes are `observed`, `manual`, `fixture`, `derived`, `assumed`, and `unavailable`. `live` and `live_validated` become `unavailable`. Fixture packets compose to `blocked`, `stale`, `partial`, `empty`, or `unavailable`, never `success`. `launchAuthorized` is always false. Missing fields and conflict notes are listed from the packet. Export omits prompts, formulas, source code, credentials, raw payloads, hidden heuristics, and cross-client data.

## Safety boundaries

- No upload endpoint, localStorage/sessionStorage persistence, provider calls, or external requests.
- No approve / spend / publish / launch controls.
- Canonical producer remains `services.market_research` / `scripts/market_research_report.py`.
