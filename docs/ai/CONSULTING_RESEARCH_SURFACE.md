# Consulting research surface

Feature path: `frontend/src/features/consulting-research-surface/`.

This is separate from draft #305 (`consulting-research-workbench`) and from the operator shell, service-delivery workbench, and cockpit owned by #298/#291/#277/#282. It does not add an API client or a backend route.

## Mount

Do not edit `Shell.tsx` or `Sidebar.tsx` from this feature. A later route owner can add one line to the existing router:

```tsx
{ path: "/operator/consulting-research", element: <ConsultingResearchSurfacePage /> }
```

Import `ConsultingResearchSurfacePage` from `frontend/src/features/consulting-research-surface/index.ts`. Until that mount exists, render `ConsultingResearchSurface` with a `consulting-research-surface-v1` packet.

## Evidence

Classes are `observed`, `manual`, `fixture`, `derived`, `assumed`, and `unavailable`. `live` and `live_validated` become `unavailable`. Fixture packets compose to `blocked`, `stale`, `partial`, `empty`, or `unavailable`, never `success`. `launchAuthorized` is always false. Missing fields and conflict notes are listed from the packet. Export omits prompts, formulas, source code, credentials, raw payloads, hidden heuristics, and cross-client data.
