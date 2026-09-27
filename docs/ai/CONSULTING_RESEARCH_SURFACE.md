# Consulting research surface

Canonical feature path: `frontend/src/features/consulting-research-surface/`.

This integration keeps one UI. Draft #314 supplied the state machine (loading, error, empty, blocked, stale, partial) and explicit conflict and missing-evidence rows. Draft #305's parallel `consulting-research-workbench` is not copied, so the two drafts do not both land. Leave #305 and #314 open until a merger closes them. Do not mount a route here. Shell, Sidebar, #298, #291, #277, and #282 are untouched.

Every adapted model sets `draft_only: true`, `live_validated: false`, and `launch_authorized: false`. Fixture evidence cannot compose to success.

## Mount

Do not edit `Shell.tsx` or `Sidebar.tsx` from this feature. A later route owner can add one line to the existing router:

```tsx
{ path: "/operator/consulting-research", element: <ConsultingResearchSurfacePage /> }
```

Import `ConsultingResearchSurfacePage` from `frontend/src/features/consulting-research-surface/index.ts`. Until that mount exists, render `ConsultingResearchSurface` with a `consulting-research-surface-v1` packet.

## Evidence

Classes are `observed`, `manual`, `fixture`, `derived`, `assumed`, and `unavailable`. `live` and `live_validated` become `unavailable`. Fixture packets compose to `blocked`, `stale`, `partial`, `empty`, or `unavailable`, never `success`. `launchAuthorized` is always false. Missing fields and conflict notes are listed from the packet. Export omits prompts, formulas, source code, credentials, raw payloads, hidden heuristics, and cross-client data.
