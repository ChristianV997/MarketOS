# Opportunity Scoring (Product Intelligence)

`backend/mvp_commerce/opportunity_scoring.py` is a deterministic, explainable
scoring and ranking engine that sits between Supplier Evidence and Commerce
MVP economics:

```text
Public Signals -> Supplier Discovery -> Supplier Evidence -> Opportunity
Scoring -> Commerce MVP economics -> Canonical Events -> Operator Dashboard
```

It composes through the existing architecture only:

- Scores `backend.mvp_commerce.opportunity.OpportunityCandidate` records —
  no new candidate model.
- Consumes `backend.mvp_commerce.supplier_evidence.SupplierEvidenceResult`
  when available — no new evidence model.
- Does not replace `backend.mvp_commerce.opportunity.select_candidate`; that
  function and the byte-identical default Commerce MVP path built on it are
  untouched. `rank_opportunities()` is a separate, opt-in alternative
  selection path.
- Emits events through the existing `backend.contracts.events.Event` /
  `backend.events.repository.EventRepository` system — no second event
  store.

## Why not "Product Intelligence"

This capability was requested under the working name "Product Intelligence
Engine." The repository already has a system that owns that exact term:
`backend/commercial_intelligence/product_analyzer.py`, which titles its
output "Product Intelligence: {product}" and is consumed by
`backend/intelligence/knowledge_graph_builder.py`,
`backend/optimization/action_generator.py`,
`backend/obsidian/sync.py::sync_product_intelligence_note`, and
`backend/workflows/stage_executor.py`. That system scores evidence from
`backend.discovery.discovery_registry`/`opportunity_registry` — the broader
discovery stack the MVP Island profile deliberately excludes (see
`docs/MVP_ISLAND.md`, "OFF in the MVP Island: ... experimental modules not
named by the profile"). Reusing that name here, while scoring a different
evidence source, would silently conflate two unrelated systems. This module
scores `mvp_commerce`'s own `OpportunityCandidate`/CJ-public-evidence
pipeline only, under its own name (`opportunity_scoring`), and never touches
`backend/commercial_intelligence/`.

## Scoring model

`score_opportunity(candidate, *, supplier_evidence=None, competition_evidence=None, margin=None, operator_override=None)`
computes 19 dimensions, each backed by a real data source or explicitly
marked unavailable — never fabricated:

| Dimension | Source | Provenance when unavailable |
|---|---|---|
| `trend_strength` | `candidate.source_local_score` | never (candidates always exist) |
| `freshness` | `candidate.recency_score` | never |
| `historical_evidence_quality` | `candidate.source_count` | never |
| `observed_information_completeness` | `candidate.assumptions`/`unknowns` counts | never |
| `supplier_evidence_quality` | best CJ ranking composite score | `unavailable` — no evidence gathered |
| `observed_supplier_cost` | `evidence.unit_cost` | `unavailable` — no observed cost |
| `assumption_count` | `candidate.assumptions` | never |
| `missing_data_penalty` | `candidate.unknowns` | never |
| `category_stability` | none exists in this repository | always `unavailable` |
| `market_saturation` | `MarketIntelligenceReport.market_saturation` | `unavailable` — no competition evidence gathered |
| `price_competitiveness` | observed competitor price dispersion | `unavailable` — no observed pricing dispersion |
| `supplier_advantage` | `MarginIntelligence.observed_supplier_advantage` | `unavailable` — no observed margin comparison |
| `market_confidence` | `MarketIntelligenceReport.confidence` | `unavailable` — no competition evidence gathered |
| `review_strength` | observed competitor rating/review density | `unavailable` — no observed rating/review data |
| `offer_diversity` | observed brand/seller diversity | `unavailable` — no observed diversity data |
| `product_simplicity` | observed CJ variant count | `unavailable` — variants not observed |
| `shipping_complexity` | observed CJ shipping cost/delivery days | `unavailable` — neither observed |
| `weight_volume` | observed CJ weight | `unavailable` — weight not observed |
| `variant_complexity` | observed CJ variant count | `unavailable` — variants not observed |

Each `ScoreDimension` carries `raw_value`, `normalized_value` (0-100),
`weight`, `contribution`, `reason`, `provenance`
(`observed`/`derived`/`assumed`/`unavailable`), and `is_unknown`.

**Composite score** (`OpportunityScore.composite_score`, 0-100) is a weighted
mean over only the *available* dimensions: base weights (see `_WEIGHTS` in
the module) are renormalized across whichever dimensions were actually
computed for a given candidate, so a candidate with no supplier evidence is
never penalized or boosted by dimensions that simply don't exist for it yet.

`category_stability` is always `unavailable`: no category-stability data
source exists anywhere in this repository. The six market-evidence
dimensions (`market_saturation` through `offer_diversity`) were added by
the Competition Intelligence follow-on — see
[Competition Intelligence](COMPETITION_INTELLIGENCE.md#opportunity-scoring-integration)
for their exact computation; they replace what was previously a single,
permanently-`unavailable` `competition_estimate` placeholder. All
unavailable dimensions are reported (never hidden) so an operator can see
exactly what evidence a score does *not* include.

## Confidence model

Confidence is deliberately a *separate* number from the composite score —
this is how the module satisfies "unknown information should reduce
confidence instead of producing fake certainty":

```text
confidence = mean(provenance_weight[dimension.provenance] for dimension in all_19_dimensions)
provenance_weight = {"observed": 1.0, "derived": 0.7, "assumed": 0.35, "unavailable": 0.0}
```

`observed_pct`/`derived_pct`/`assumed_pct`/`unknown_pct` on `OpportunityScore`
report the same breakdown as percentages, so an operator can see exactly how
much of a score rests on observation versus assumption versus nothing at
all.

Without any supplier or competition evidence, six candidate-only
dimensions are always available (one `observed`, five `derived`), which
floors confidence at `(1.0 + 5*0.7) / 19 ≈ 0.24` for any candidate —
gathering supplier and/or competition evidence is the only way to raise it
further, and gathering evidence with only `assumed`-tier data (e.g.
dry-run/degraded fetches) raises it only slightly. This floor dropped from
~0.32 (over 14 dimensions) to ~0.24 (over 19) when the Competition
Intelligence dimensions were added — more of the picture is now honestly
represented as unknown by default, which correspondingly made the `< 0.3`
"gather more evidence" recommended-action threshold reachable without any
evidence at all (previously unreachable; see `docs/COMPETITION_INTELLIGENCE.md`).

## Ranking algorithm

`rank_opportunities(candidates, *, workspace_id, query, supplier_evidence_by_candidate=None, operator_overrides=None, generated_at=None)`
scores every candidate independently and sorts by
`(-effective_score, candidate_id)` — ties break on `candidate_id` ascending,
matching the existing tie-break convention in
`backend.mvp_commerce.opportunity.select_candidate`. It is pure and
deterministic: identical inputs always produce an identical
`OpportunityAssessment`, including event IDs (sha256-derived from
`run_id` + a fixed suffix per event).

`effective_score` is the composite score unless an `operator_override` with
a `"score"` key is supplied, in which case the override value is used for
ranking while the computed composite/dimensions remain on the object,
unaltered, for audit — an override never erases the underlying evidence.

## Operator interpretation

- **`recommended_action`**: `advance_to_economics_review` when confidence
  ≥ 0.6 and composite ≥ 60; `gather_more_evidence_before_any_decision` when
  confidence < 0.3; `corroborate_before_advancing` otherwise.
- **`reasons`**: the top 3 available dimensions by contribution — why this
  candidate scored where it did.
- **`risks`**: available dimensions scoring below 40 (normalized).
- **`unknowns`**: every `unavailable` dimension, with its reason — what
  evidence this score is missing.
- **`blockers`**: carried through from `candidate.cannot_claim` (e.g. "No
  demand, sales, ROAS, ... claim is supported").

None of this output is authoritative: every emitted event carries
`dry_run: True, advisory: True, non_authoritative: True,
no_launch_authority: True, no_spend_authority: True, no_order_authority:
True`.

## Commerce MVP integration

`run_commerce_mvp_slice(..., use_opportunity_ranking: bool = False)` and
`run_commerce_mvp_from_public_rss(..., use_opportunity_ranking: bool =
False)` are opt-in. With the default `False`, behavior is byte-for-byte
identical to before this capability existed: `select_candidate()` picks the
single highest-source-score candidate, exactly as before.

With `use_opportunity_ranking=True`:

1. A provisional candidate is selected via the existing
   `select_candidate()` — this is only used to key any supplier evidence
   the caller passed in (evidence is always gathered for one specific
   product, never re-attributed).
2. `rank_opportunities()` scores every candidate and picks
   `top_candidate_id` as the run's `selected_candidate` — which may differ
   from `select_candidate()`'s pick when supplier evidence or dimension
   scoring favors a different candidate.
3. Unit economics use whichever supplier evidence was actually keyed to the
   *selected* candidate (never a mismatched candidate's evidence).
4. `OpportunityAssessment.to_dict()` is stored in
   `CommerceMvpRun.metadata["opportunity_assessment"]`.
5. `opportunity_scoring_events()` are appended alongside the existing
   `commerce_mvp_events()`.

`api/routes/commerce_mvp.py`'s `POST /api/commerce-mvp/public-run` accepts
`use_opportunity_ranking: bool = false` and reports
`opportunity_ranking_used` in its response. Unlike supplier evidence, this
flag needs no server-side live-mode gate: it is pure computation over
already-gathered evidence, with no network calls of its own.

## Canonical events

`opportunity_scoring_events(assessment, *, run_id)` emits, in order:

1. `opportunity_scoring_started` — once, with `candidate_count`/`query`.
2. `candidate_scored` — once per candidate, payload = `OpportunityScore.to_dict()`.
3. `opportunity_ranked` — once, with `top_candidate_id` and the full ranking order.
4. `opportunity_scoring_completed` — once, with `top_candidate_id`.

Event IDs are `"opportunity-scoring-" + sha256(f"{run_id}:{suffix}")[:20]` —
deterministic replay: re-running the same assessment through the same
`run_id` produces identical event IDs.

## Read API and dashboard view

Two read routes exist, following the existing `query_service.py` patterns:

- `GET /api/events/opportunity-scoring` — a thin `event_type` filter over
  the generic timeline (same pattern as the existing
  `/api/events/supplier-evidence`). Fast, but the generic timeline redacts
  payloads to `{"keys": [...], "item_count": N}` — useful for presence/
  count checks, not for reading actual scores.
- `GET /api/events/opportunity-rankings` — decoded summaries via
  `backend.events.query_service.build_opportunity_ranking_summaries()`,
  following the same pattern as `build_commerce_run_summaries`/
  `build_shopify_import_summaries`. This is the route that carries real
  score/confidence/dimension data, because an operator needs to see *why*
  a candidate ranked first, not just that a `candidate_scored` event
  happened.

### Dashboard view

The **Opportunity ranking** tab in `/operator/events`
(`frontend/src/pages/OperatorEventDashboard.tsx`) reads
`/api/events/opportunity-rankings` and renders, per run: each candidate's
composite score, confidence, observed/derived/assumed/unknown percentage
split, recommended action, top reasons, risks, unknowns, and an expandable
per-dimension breakdown table. The top-ranked candidate is visually marked
"Recommended candidate." The **Run public Commerce MVP test** form has a
**Rank candidates with opportunity scoring** checkbox that sets
`use_opportunity_ranking` on the request.

## Testing

- `tests/test_opportunity_scoring.py` — dimension computation (with/without
  evidence), unavailable-dimension handling, confidence/composite math,
  recommended-action thresholds, operator overrides, ranking (ordering,
  ties, empty input, evidence-to-candidate keying), event emission
  (ordering, correlation, determinism, advisory metadata), `to_dict()`.
- `tests/integration/test_opportunity_ranking_commerce_mvp.py` — the
  `use_opportunity_ranking` runner param: byte-identical default behavior,
  correct candidate selection, correct evidence keying, event emission,
  empty-candidate fallback, deterministic replay.
- `tests/integration/test_commerce_mvp_public_network_runner.py` — the
  public-RSS-path opt-in (added cases only; existing cases unchanged).
- `tests/integration/test_commerce_mvp_public_run_api.py` — the API request
  field's propagation and reporting (added cases only).
- `tests/integration/test_opportunity_scoring_read_api.py` — both read
  routes: filtering, rate limiting, route registration.
- `tests/contracts/test_opportunity_ranking_summaries.py` —
  `build_opportunity_ranking_summaries()`: decoded score data, ranking
  order, JSON-safety, unrelated-event exclusion, `event_query_report()`
  wiring.

No existing test was modified to make room for these; the Competition
Intelligence follow-on later updated three of these tests' hardcoded
dimension counts/confidence thresholds to reflect the new 19-dimension
total (see `docs/COMPETITION_INTELLIGENCE.md`) — a reflection of real,
intentional behavior change, not a workaround. All pre-existing Commerce
MVP, supplier-evidence, and canonical-event tests still pass unchanged.

## Future extensions

- `category_stability` remains permanently `unavailable` until a real
  category-stability data source exists in this repository — do not fill
  it with a heuristic; that would fabricate certainty this module is
  explicitly designed never to produce. (`competition_estimate` was
  replaced by six real dimensions fed from Competition Intelligence — see
  `docs/COMPETITION_INTELLIGENCE.md`.)
- Score visualization (trend lines across repeated runs of the same query)
  and evidence drill-down (linking a `candidate_scored` event directly to
  its underlying `supplier_product_observed` event) are natural follow-ons
  once there is real multi-run history to visualize — not built here to
  avoid speculating ahead of actual usage.
- `operator_overrides` is accepted end-to-end by `rank_opportunities()` but
  has no UI or persistence path yet; an operator can only supply one today
  by calling the Python API directly.
