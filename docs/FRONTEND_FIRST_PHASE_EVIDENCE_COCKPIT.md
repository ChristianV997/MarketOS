# Frontend first-phase evidence cockpit

Read-only operator surface stacked on PR #213 frontend/API authority.

## Route

- `/operator/first-phase`

## Operator capabilities (integration-03)

- Ranked candidate table with pillar-level evidence columns (server order preserved)
- Bounded windowing (50 rows) for larger ranked sets — no client re-ranking
- Filters: search, risk, commercial decision, top-candidate only, stable top-10 (`useDeferredValue` / `useTransition`)
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
- Decision-review timeline, promotion/blocker tags, and display-only next-action workflow
- Optional #250 `MarketOS.ClientCommerceProjection.v1` overlay by `candidate_id` (never a second API client)

## Data sources (existing API authority)

Composed via `useCanonicalEvents` hooks only:

- `GET /api/phase1/readiness`
- `GET /api/phase1/benchmark-matrix`
- `GET /api/phase1/public-market-benchmark`
- `GET /api/events/research-portfolio`

The frontend **never** recalculates rankings, never grants launch authority, and never calls providers directly.

`origin/main` (`df59a06`) exposes Phase 1 readiness/benchmark routes. It does **not** expose
`GET /api/phase1/evidence-cockpit`. The cockpit therefore remains a composed-live view plus an
optional overlay of a supplied `product-validation-report-v1` packet. Do not treat the overlay
as a live API.

## Stack / route conflict with PR #213

#230 stays stacked on #213 (`70ffc9f`). Unique cockpit commits do **not** absorb #213 files.
The only shared frontend files touched on top of #213 are additive navigation:

- `frontend/src/main.tsx` adds `/operator/first-phase`
- `frontend/src/components/layout/Sidebar.tsx` adds the First-phase cockpit nav item

No #213 routes are renamed or removed. Merge #213 first; then #230 is a fast-forward-style
stack of cockpit files plus those two nav lines.

## Contract fixture matrix

Deterministic fixtures live in `frontend/src/features/first-phase-cockpit/fixtures/projection-matrix/`.
They follow the existing #247 report/appendix shape (not a second packet):

| Fixture | Expected |
|---------|----------|
| `accepted-manual-screening.json` | Overlay SKU/lane/offer; overall confidence stays unavailable (not averaged) |
| `accepted-backend-audit-shape.json` | Fixture/contract-shaped #247 `candidate_audit` (`action`, `evidence_gaps`, `promotion_lifecycle`, `evidence_refs`); compose+view-model join only, never producer output |
| `partial-appendix.json` | Accepted; server rows unchanged |
| `stale-unmatched.json` | Expired/blocked economics unavailable; report-only IDs not inserted |
| `rejected-unsupported-version.json` | `schema_version_unsupported` |
| `rejected-duplicate-ids.json` | `candidate_identity_duplicate` |
| `rejected-secret.json` | `secret_shaped_value_rejected` |
| `rejected-malformed.json` | `candidate_audit_malformed` |
| `rejected-launch-authorized.json` | `launch_authorized_rejected` |

Screening fixture evidence is never commercial validation.

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

Reference-only; no vendored code and no second data layer.

| Pattern | Use | License / source |
|---------|-----|------------------|
| WAI-ARIA APG Grid | roving tabindex, `aria-selected`, caption, skip link | [W3C Software and Document License](https://www.w3.org/copyright/software-license-2023/) — [APG Grid Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/grid/) |
| React Aria Collections | keyboard activation + focus handoff concepts | Apache-2.0 — https://react-spectrum.adobe.com/react-aria/ |
| TanStack Table | filter/window without mutating sort order; stable top-N | MIT — https://tanstack.com/table/latest |
| Storybook CSF | deterministic fixture matrix + normalized snapshots | MIT — https://storybook.js.org/docs/writing-stories |
| Radix focus/label | visible focus ring, labelled sections, non-modal detail | MIT — https://www.radix-ui.com/primitives/docs/overview/accessibility |
| WAI-ARIA APG list/status | timeline as ordered list; next-action as description list + live status | [W3C Software and Document License](https://www.w3.org/copyright/software-license-2023/) |
| Stale/partial UI | explicit banners; unmatched rows announced, never invented | operator-local; no extra library |

## Commercial decision review (V6)

The cockpit is a read-only review surface, not a ranked-score editor.

- Timeline kinds are always rendered; missing projection fields stay `unavailable` with `at: null`.
  Declared `freshness: expired` is copied as a stale label when `evidence_expiry` is absent; no timestamp is invented.
- Promotion tags distinguish screening / needs_evidence / hold / reject / blocked /
  draft_ready / launch_authorized_false / unavailable / stale / fixture / manual_import /
  simulated / live_readonly / live_validated. Weaker evidence is never upgraded.
- Next-action workflow shows action, missing evidence, responsible party, expected evidence type,
  human-confirmation, and `allowedInReadOnlyCockpit: false`. Future actions stay draft/unavailable
  metadata. No mutation buttons.
- #247 overlay remains `product-validation-report-v1` and rejects `cross_workspace_rejected`
  when an operator workspace is known and the packet or audit declares a different workspace.
  Candidate `action` aliases `next_action`; `evidence_gaps` join missing evidence; `promotion_lifecycle`
  is copied as display-only transitions without inventing timeline timestamps. #250 overlay is
  `MarketOS.ClientCommerceProjection.v1` only. Malformed, secret-shaped, duplicate, oversized,
  cross-workspace, or `launch_authorized: true` packets are rejected with the exact warning token.
- `commerceProjection` is not fetched. Until a cockpit-owned endpoint exists, the hook passes
  `undefined` and the UI records `commerce_client_projection_unavailable`.

## Safety

- Read-only / advisory only
- No credentials in browser
- No ads, orders, payments, inventory, publishing, messaging, or provider controls
- Export rejects secret-shaped values, prompt/formula/heuristic keys, filesystem paths, and raw provider payloads
