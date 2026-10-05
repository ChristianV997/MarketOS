# Owner research: opportunity review and curated portfolio (frontend slice)

Status: **implemented, unit/component tested, browser-checked in a throwaway
harness (not in CI), NOT mounted, NOT integration-tested against a backend, NOT
live validated.**

| Capability level | State |
|---|---|
| Implemented | yes (isolated feature directory) |
| Unit / component tested | yes (`npm test`; adapters, gate, listbox keys, live-region text, SSR of the real components, AST guards) |
| Browser-checked (real Chromium, all network mocked) | yes, with a throwaway harness that is **not committed** and not in CI |
| Integration-tested against a real backend | **no**: the portfolio route does not exist and the canonical reads were mocked |
| Mounted / reachable in the app | **no** |
| Live validated | **no** |

This is the owner's research-led workspace surface. It is separate from the
client-services CRM and shares no state with it. It is advisory and read-only:
no publishing, spend, orders, provider calls or data changes.

## Where it lives

`frontend/src/features/owner-research-portfolio/` (new, isolated directory)

| Path | Role |
|---|---|
| `contracts/ownerResearch.ts` | view-model types, portfolio contract, constants |
| `lib/adaptRankingReadModel.ts` | canonical ranking packet -> review model |
| `lib/adaptPortfolioReadModel.ts` | untrusted portfolio payload -> progress model; draft-research gate |
| `lib/portfolioApi.ts` | GET-only fetch adapter (injectable `fetch`) |
| `lib/freshnessView.ts`, `format.ts`, `candidateId.ts`, `stateCopy.ts` | helpers and copy |
| `lib/listboxKeys.ts` | pure keyboard resolver for the ranked listbox |
| `lib/announce.ts` | one-sentence text for the persistent live region |
| `components/` | `OwnerResearchWorkspace`, `RankedOpportunityList`, `OpportunityDetail`, `PortfolioProgressPanel`, `SurfaceStateBanner` |
| `hooks/useOwnerPortfolio.ts` | one GET per load (plus one per explicit refresh), abortable, request-keyed |
| `hooks/useNow.ts` | shared 60-second clock so freshness ages on a long-lived page |
| `OwnerResearchPortfolioPage.tsx` | container (default export) |
| `fixtures/ownerResearchFixtures.ts` | always-labelled fixture data, only used on explicit request |

Tests: `frontend/tests/owner-research-portfolio.adapters.test.mjs`,
`frontend/tests/owner-research-portfolio.components.test.mjs`, with a test-only
TS/TSX loader in `frontend/tests/helpers/`.

## Contract consumed

### 1. Ranking read model (canonical, exists)

`FirstPhaseEvidencePacket` from
`frontend/src/features/first-phase-cockpit/contracts/firstPhaseEvidencePacket.ts`
(`phase1-evidence-cockpit-v1` view model), obtained through the existing
`useFirstPhaseEvidenceCockpit()` hook. Its server route
`GET /api/phase1/evidence-cockpit` is documented as **not implemented**, so the
packet is composed client-side from existing canonical read endpoints. This
slice does not add a second ranking path.

Fields read: `state`, `rankedCandidates[]` (`candidateId`, `title`, `rankIndex`,
`pillarCells[]`, `missingEvidence`, `hardGates`, `conflicts`, `assumptions`,
`evidenceMode`, `evidenceClass`, `supplierEvidenceClass`,
`consumerEvidenceClass`, `evidenceReferences`, `replayIdentity`,
`freshnessExpiry`, `promotionState`, `commercialDecision`, `riskLevel`,
`nextBestAction`, `evidenceCompleteness`, `confidence`), `fingerprint`
(`evidenceMode`, `readOnly`, `networkCalls`, `generatedAt`, `freshnessLabel`,
`schemaVersion`, `reportVersion`, `sourceLabels`), `blockedReasons`,
`unavailableReasons`, `warnings`.

Rules: backend order is the ranking (never re-sorted); no score is computed,
blended or backfilled; a missing value is "Not reported", never zero; ids are
exact (no trimming, case-folding, or derivation from title/SKU); duplicate or
malformed ids are dropped and flagged; a packet with `fingerprint.readOnly !==
true` is refused. Rows the list leaves out are named on screen, not only
counted: the notice reads e.g. "2 ranked rows not shown: 1 duplicate candidate
ID, 1 malformed candidate ID", and rows past the 200-row display limit are
counted individually (a 205-row packet reports 5, not 1). The exact markers
(`duplicate_candidate_id:<id>`, `rank_order_inconsistent:<id>`, ...) are listed
in the collapsible ranking details.

### 2. Portfolio read model (PROPOSED, not served by any route on main)

Schema `owner-research-portfolio-v1`, proposed path
`GET /api/owner-research/portfolio?workspace_id=<id>`.

```jsonc
{
  "schema_version": "owner-research-portfolio-v1",
  "workspace_id": "ws-…",            // must equal the requested workspace
  "generated_at": "2026-09-29T11:00:00Z",   // optional
  "expires_at": "2026-09-29T12:00:00Z",     // optional; else 24h age from generated_at
  "evidence_mode": "fixture_only | simulated | manual | live_readonly",
  "items": [
    { "candidate_id": "…", "status": "active | inactive | removed | archived",
      "sku": "…", "supplier_offer_count": 3, "quantity": 40 }   // extras ignored
  ],
  "draft_research": { "eligible": true, "reasons": ["…"] },     // backend-owned
  "read_only": true,
  "mutated": false
}
```

* A 404/405/501 is `unavailable` (`endpoint_not_available`); any other failure
  is `error`. Neither is ever rendered as an empty portfolio.
* Rejected as `error`: non-object, unsupported `schema_version`,
  `read_only !== true` or `mutated !== false`, credential-shaped keys,
  `workspace_id` missing or different from the request, non-array or more than
  500 `items`, and a payload too deep or too large to scan for credential-shaped
  keys (`payload_too_complex`, fail closed). Responses over the size cap are
  `payload_too_large`.
* No workspace selected => `unavailable` (`workspace_not_selected`); there is no
  ambient default tenant. The **requested** workspace is authoritative: a payload
  for any other workspace is `workspace_mismatch`, never counted.
* The hook keys every outcome by workspace and request, so a slow response for
  workspace A is never shown (or flagged as a mismatch) after switching to B.

## Progress and eligibility

* **X/3 counts distinct, active, well-formed `candidate_id` values only.** SKUs,
  supplier offers, quantities, repeated rows, inactive/removed/archived entries,
  and malformed ids never add to it. Case variants are distinct ids (identity is
  exact). More than three shows honestly (`5/3`) with the bar clamped.
* Unknown (loading/unavailable/error) shows `—/3`, never `0/3`. A loaded
  portfolio with no active candidates is a real `0/3`.
* **Draft-research actions are native-disabled unless every condition holds:**
  the portfolio is loaded, not fixture/simulated, not stale, its freshness is not
  invalid, no entries were ignored as invalid (`partial`), provenance is known,
  the backend explicitly reported a strict boolean `eligible: true`, that does
  not conflict with the distinct active count (`eligible: true` with fewer than
  three distinct active ids is a conflict, not an unlock), and an
  `onDraftResearch` handler is connected. `manual` evidence and an unreported
  freshness do not block; both stay labelled. Three active ids alone never unlock
  anything. Every unmet condition is listed on screen, and fixture data that
  "reports" eligibility is described as a simulation, not a backend decision.
* The click handler re-checks the gate and emits `{ actionId,
  activeCandidateIds }` (a copy of the distinct ids) and nothing else. The page
  itself performs no request when an action is used.

## States

Phase (exclusive, one banner per scope): `loading`, `error`, `unavailable`,
`empty`, `ready`. Qualifiers (may co-occur): `fixture`, `stale`, `partial`,
`blocked`. Each qualifier has distinct copy and appears **once**, merged across
the ranking and portfolio scopes with an "Applies to" line. Errors use
`role="alert"`; the rest `role="status"`. Backend reason codes are listed under
each scope and are expanded by default for `error`, `unavailable` and `blocked`.

A single persistent, visually hidden `role="status" aria-live="polite"` region
announces loading -> ready and count changes in one sentence (for example
"Ranking ready: 5 candidates in backend order. Portfolio: 2 of 3 distinct active
candidates. Notices: fixture, stale, partial."). An unknown portfolio is announced as loading,
failed or unavailable, never as zero. The shared clock re-evaluates freshness
every minute, so a portfolio that was fresh when loaded turns stale (and drafting
disables) without a refetch.

## Layout and keyboard

* Ranked candidates are a single-select `listbox` with a roving tabindex:
  ArrowUp/ArrowDown/Home/End move selection and focus (no wrap-around), Enter or
  Space hand focus to the details region. Ctrl/Cmd/Alt combinations are left to
  the browser. Each option's accessible name carries rank, title, evidence class
  and state; the candidate id is its description. Below `lg` the list and
  details stack, with a "Jump to selected candidate details" link before and
  after the list; at `lg` they sit side by side and the links are hidden.
* Evidence pillars are a reflowing list (not a table), so there is no
  horizontal scroll region at any width. Long backend tokens wrap.
* Interactive targets are at least 44px tall.

## Not mounted: integration dependencies

Nothing imports this feature. It is **not routed and not in the sidebar**; the
shared routing, Sidebar, Shell and API-origin files were intentionally not
edited. To make it reachable:

1. Add a route element for `OwnerResearchPortfolioPage` in
   `frontend/src/main.tsx`, and a navigation entry in the shell (separate,
   reviewed change). Render it inside the shell's `<main>` landmark: the feature
   deliberately renders none of its own (an axe audit of a bare page flags
   `landmark-one-main`; it is clean once wrapped in `<main>`).
2. Backend: serve `owner-research-portfolio-v1` (above) with workspace scoping
   and an explicit `draft_research.eligible` decision. Until then the portfolio
   panel truthfully reports `unavailable`.
3. Tenant identity: decide how a workspace is selected (`?workspace_id=` is read
   today; there is no default). Workspace ids are currently name-derived.
4. Draft research: provide a service and pass `onDraftResearch`; without it the
   actions stay disabled even when the backend reports eligibility.
5. Optional: `generatedAt` is `null` in the composed-live ranking packet, so
   ranking freshness reads "not reported" until the backend supplies it.

## Verification

```
cd frontend
npm run typecheck
npm test            # includes the two owner-research-portfolio test files
npm run build
```

`?source=fixture` (or `source="fixture"`) renders labelled fixture data and
never enables draft research.

Not covered by CI: event-driven keyboard behaviour, responsive layout and an
axe-core audit were checked in real Chromium with a throwaway Vite harness and
mocked network (the harness lives outside the repository). If this page is
mounted, an equivalent browser test should be added to the app's own e2e suite.
