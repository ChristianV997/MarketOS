# Frontend first-phase evidence cockpit

Read-only operator surface stacked on PR #213 frontend/API authority.

## Route

- `/operator/first-phase`

## Operator capabilities (integration-03)

- Ranked candidate table with pillar-level evidence columns (server order preserved)
- Bounded windowing (50 rows) for larger ranked sets — no client re-ranking
- Filters: search, risk, commercial decision, top-candidate only (`useDeferredValue` / `useTransition`)
- Keyboard selection with roving tabindex (ArrowUp/Down, Home/End, Enter/Space) + detail focus handoff
- Responsive mobile card list + desktop evidence grid
- Evidence pillars: provenance, freshness, source family, evidence mode, evidence class
  (`fixture`, `assumption`, `derived`, `public_observed`, `supplier_claimed`,
  `supplier_documented`, `sample_verified`, `direct_ship_verified`, `live_order_verified`,
  `live_sales_validated`, `unavailable`, `blocked`)
- Candidate identity, exact SKU (when present), market lane, supplier offer, economics,
  competition, consumer attention, assumptions, missing evidence, conflicts, confidence,
  promotion/risk, next-best action
- Evidence classes also include `stale` and `not_run`. The client never upgrades evidence.
- Maps existing PR #247 `product-validation-report-v1` + `appendix.research_to_decision_version: v1`
  onto server-ordered rows by `candidate_id`. Missing fields render as unavailable; confidence is
  not averaged. Replay fingerprint is display-only SHA-256 hex.
- No second API client: the projection is optional overlay input, not a new fetch.
- TrustOS / Governor / Approval Ledger panels (explicit unavailable until merged packet)
- States: loading, empty, blocked, unavailable, stale, **partial**, success
- Schema-version gated future packet validator (`phase1-evidence-cockpit-v1`) — endpoint not claimed to exist
- Deterministic freshness labels + client-safe JSON export
- Normalized render model for contract snapshots

## Data sources (existing API authority)

Composed via `useCanonicalEvents` hooks only:

- `GET /api/phase1/readiness`
- `GET /api/phase1/benchmark-matrix`
- `GET /api/phase1/public-market-benchmark`
- `GET /api/events/research-portfolio`

The frontend **never** recalculates rankings, never grants launch authority, and never calls providers directly.

## Future merged packet

When backend merges a single packet, validate with `validateEvidenceCockpitApiPacket` then map with
`mapApiPacketToViewModel`. Required:

```
schema_version: "phase1-evidence-cockpit-v1"
GET /api/phase1/evidence-cockpit   # not implemented in this lane
```

Until that endpoint exists, control planes and consumer attention remain explicit `unavailable`.
Malformed / unsupported schema / out-of-order rank_index / secret-shaped values are rejected fail-closed.

## Public patterns adapted (no new dependencies)

- WAI-ARIA APG / React Aria: roving tabindex, grid semantics, skip link, focus handoff to detail
- TanStack Table concepts: filter + window without mutating sort order
- Radix-style labeled focus-visible controls (plain HTML)
- Storybook-style deterministic fixture + normalized render model
- Vite/same-origin proxy unchanged from PR #213

## Safety

- Read-only / advisory only
- No credentials in browser
- No ads, orders, payments, inventory, publishing, messaging, or provider controls
- Export rejects secret-shaped values, prompt/formula/heuristic keys, filesystem paths, and raw provider payloads
