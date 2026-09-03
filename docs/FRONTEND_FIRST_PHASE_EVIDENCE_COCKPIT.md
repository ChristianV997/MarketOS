# Frontend first-phase evidence cockpit

Read-only operator surface stacked on PR #213 frontend/API authority.

## Route

- `/operator/first-phase`

## Operator capabilities (v2)

- Ranked candidate table with pillar-level evidence columns (server order preserved)
- Filters: search, risk, commercial decision, top-candidate only (never re-ranks)
- Keyboard selection (ArrowUp/ArrowDown/Enter/Space) and candidate detail panel
- Evidence pillars with provenance, freshness, source family, and evidence mode
- TrustOS / Governor / Approval Ledger status panels (explicit unavailable until merged packet)
- Deterministic run metadata (fingerprint, source labels/families, blocked/unavailable reasons)
- Client-safe JSON export of already-sanitized view-model fields
- States: loading, empty, blocked, unavailable, stale, success
- Accessibility: skip link, captions, `scope` headers, `aria-live` status, labeled controls

## Data sources (existing API authority)

The cockpit composes existing read-only endpoints via `useCanonicalEvents` hooks:

- `GET /api/phase1/readiness`
- `GET /api/phase1/benchmark-matrix`
- `GET /api/phase1/public-market-benchmark`
- `GET /api/events/research-portfolio`

The frontend **never** recalculates rankings, never grants launch authority, and never calls providers directly.

## Future merged packet

When backend merges a single packet, map it through
`validateEvidenceCockpitApiPacket` → `mapApiPacketToViewModel` in
`frontend/src/features/first-phase-cockpit/lib/validateEvidencePacket.ts`:

```
GET /api/phase1/evidence-cockpit
```

Required slots (aligned to existing `to_dict` / `client_safe` projections):

- ranked candidates (server `rank_index` preserved)
- evidence pillars (market, consumer attention, supplier, economics, provenance, freshness)
- TrustOS result (`TrustOSReport.to_dict(client_safe=True)` summary fields only)
- Governor result (`ResourceExecutionGovernorReport.to_dict()` offline simulation)
- Approval Ledger status
- deterministic fingerprint metadata (`report_version`, `generated_at`, `source_labels`, `source_families`)

Until that endpoint exists, TrustOS/Governor/Approval Ledger render as explicit `unavailable` slots and consumer attention is marked unavailable. Malformed packets are rejected fail-closed.

## Public patterns adapted (no new dependencies)

- React Aria / WAI-ARIA APG: grid/table selection via `aria-selected`, keyboard arrows, captions, skip link
- TanStack Table concepts: column model + filter without mutating sort order (implemented as plain filter loop)
- Radix-style labeled controls and focus-visible rings without adding Radix
- Storybook-style deterministic fixture (`demoPacket.ts`) for offline review
- Vite/same-origin proxy unchanged from PR #213 authority

## Safety

- Read-only / advisory only
- No credentials in browser
- No ads, orders, payments, publishing, or messaging controls
- Export rejects secret-shaped values
