# Frontend first-phase evidence cockpit

Read-only operator surface stacked on PR #213 frontend/API authority.

## Route

- `/operator/first-phase`

## Data sources (existing API authority)

The cockpit composes existing read-only endpoints via `useCanonicalEvents` hooks:

- `GET /api/phase1/readiness`
- `GET /api/phase1/benchmark-matrix`
- `GET /api/phase1/public-market-benchmark`
- `GET /api/events/research-portfolio`

The frontend **never** recalculates rankings, never grants launch authority, and never calls providers directly.

## Future merged packet

When backend merges a single packet, map it to `FirstPhaseEvidenceCockpitApiContract` in
`frontend/src/features/first-phase-cockpit/contracts/firstPhaseEvidencePacket.ts`:

```
GET /api/phase1/evidence-cockpit
```

Required slots:

- ranked candidates (server order preserved)
- evidence pillars (market, consumer attention, supplier, economics, provenance, freshness)
- TrustOS result (read-only)
- Governor result (offline simulation only)
- Approval Ledger status
- deterministic fingerprint metadata (`report_version`, `generated_at`, `source_labels`)

Until that endpoint exists, TrustOS/Governor/Approval Ledger render as explicit `unavailable` slots and consumer attention is marked unavailable.

## Safety

- Read-only / advisory only
- No credentials in browser
- No ads, orders, payments, publishing, or messaging controls
