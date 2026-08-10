# Product Research Intelligence Engine

`backend/mvp_commerce/product_research.py` is the missing large-scale
candidate discovery and prioritization capability — it transforms
scattered per-candidate observations (Public Signals -> Supplier Evidence
-> Competition Intelligence -> Opportunity Scoring) into a ranked research
portfolio:

```text
Public Signals -> Supplier Evidence -> Competition Intelligence ->
Opportunity Scoring -> Product Research (this module) -> Commerce MVP
```

## Repository audit and reuse decisions

- `backend/mvp_commerce/opportunity_scoring.py`'s `OpportunityCandidate`/
  `OpportunityScore`, `backend/mvp_commerce/supplier_evidence.py`'s
  `SupplierEvidenceResult`, and `backend/mvp_commerce/competition_intelligence.py`'s
  `MarketIntelligenceReport` are **wrapped**, never duplicated. `ResearchCandidate`
  composes references to these existing objects; scoring is never
  recomputed here.
- **`backend/discovery/discovery_registry.py`/`opportunity_registry.py`**:
  checked for class-name/API collisions (`DiscoveryRegistry`,
  `OpportunityRegistry`) — none found. No clustering, identity-resolution,
  or portfolio-construction logic exists anywhere in `backend/discovery/`
  today; this is genuinely new capability, not a duplicate.
- **`backend/commercial/product_research.py::run_product_research()`**:
  a small, separate, explicitly `"status": "not_connected"` placeholder
  scaffold in an unrelated package — no dataclasses, no events, no
  evidence aggregation of its own. This module is the actually-wired
  engine; the two never call each other. See this module's own docstring
  for the full distinction.
- Continues the precedent set by `opportunity_scoring.py`/
  `competition_intelligence.py`: not wired into
  `backend/commercial_intelligence/`'s heavier `discovery_registry`-based
  stack (one of the "OFF in the MVP Island" experimental modules,
  `docs/MVP_ISLAND.md`).

## OSS research

Evaluated for product clustering / duplicate detection / semantic
similarity / entity resolution:

- **`dedupe`** (dedupeio/dedupe, mature, active-learning based fuzzy
  matching) — rejected: requires labeled training data and an interactive
  learning loop, unsuitable for a fully deterministic, no-training system
  where "never merge uncertain products silently" must hold from the
  first run with zero prior labels.
- **`recordlinkage`** — rejected: Pandas-based record-linkage framework
  designed for linking rows across structured datasets with configurable
  comparison pipelines; would add a new dependency and a second
  comparison-pipeline abstraction for a problem scikit-learn (already a
  pinned dependency) already solves for short product-title strings.
- **`rapidfuzz`/`thefuzz`/`python-Levenshtein`** (string similarity) —
  rejected: not currently a dependency of this repository; scikit-learn's
  character-n-gram TF-IDF + cosine similarity is an equally
  production-proven technique for short-string fuzzy matching (the same
  underlying idea entity-resolution libraries use), and needs no new
  install.
- **Adopted**: `scikit-learn` (`TfidfVectorizer(analyzer="char_wb",
  ngram_range=(2,4))` + `cosine_similarity`) — already pinned in
  `requirements.txt` for other subsystems in this repository, deterministic
  (no randomness), and robust to minor title variation ("Portable Espresso
  Maker" vs. "Portable Espresso Machine") in a way plain word-level Jaccard
  similarity is not. Used once per call to build a full pairwise similarity
  matrix (`_similarity_matrix()`), then connected-component clustering
  (a standard, well-established entity-resolution architecture — "blocking
  + pairwise similarity + threshold clustering" — implemented here with
  plain union-find, no additional library) turns that matrix into groups.
- **General entity-resolution architecture** (adopted as an *idea*, not a
  library): the standard pattern of blocking, pairwise similarity scoring,
  and threshold-gated clustering — reflected directly in
  `group_duplicates()`/`build_clusters()`'s design.

## Repository-shape discovery during implementation

`OpportunityCandidate.category_name` (from
`backend.mvp_commerce.opportunity.build_opportunity_candidates_from_signals`)
is **always** the literal constant `"public_signal_hypothesis"` in this
pipeline — a source-type tag, not a real product taxonomy value. An early
version of `build_clusters()` partitioned candidates by this field first
(a real product-taxonomy field would make that a sensible coarse
partition); testing end-to-end against real fixture data caught that this
put every candidate in one meaningless bucket and produced cluster names
like `"public signal hypothesis"`. Fixed before this was ever considered
done: clustering now relies on title similarity alone;
`normalize_category()` still processes whatever value is present so a
future evidence source with a real category populates
`common_attributes.category_tags` correctly, but nothing depends on it for
partitioning today. Documented here so the next contributor doesn't
rediscover this the hard way.

## Product Research Engine

`ResearchCandidate` aggregates evidence from as many or as few sources as
have actually been gathered — `opportunity_candidate` (required),
`opportunity_score`, `supplier_evidence`, `competition_evidence` (all
optional), plus a generic `additional_evidence: dict[str, Any]` bag for
forward compatibility (e.g. a future Shopify read-only context snippet)
without changing this dataclass's shape. `build_research_candidates()` is
pure aggregation — no fetching, no scoring.

## Identity Resolution

`normalize_title()`/`normalize_brand()`/`normalize_category()` are
deterministic, stdlib-only (lowercase, strip punctuation/stopwords/brand
suffixes, collapse whitespace). `resolve_identity()` returns a
`ProductIdentity` with a `confidence` reflecting how many of the three
fields actually had real data — never a guess at similarity itself.
Brand can currently only come from observed Competition Intelligence
(`CompetitorOffer.brand`); without competition evidence, `normalized_brand`
is honestly empty.

## Product Clustering

`group_duplicates(candidates, *, duplicate_threshold=0.85, variant_threshold=0.55)`
never merges two candidates below `variant_threshold` — anything below
stays its own singleton `"unique"` group. Above the variant threshold but
below the duplicate threshold is labeled `"variant"` (same family,
distinct product — e.g. a battery vs. manual espresso maker); above the
duplicate threshold is `"duplicate"` (near-identical listings).

`build_clusters(candidates, *, threshold=0.55)` groups by title similarity
via connected components (deterministic union-find), exposing per cluster:
`confidence` (mean pairwise similarity), `member_count`
(`len(member_ids)`), `representative_id` (lexicographically smallest
member), `common_attributes` (shared brands/category tags),
`price_range` (min/max/median across members' observed supplier cost or
market median price), `supplier_diversity`/`competition_diversity`
(distinct sources across members).

## Research Quality

`compute_research_quality()` computes, from real counts only (never
fabricated): `evidence_coverage`, `supplier_coverage`,
`competition_coverage`, `observed_pricing_coverage`, `market_confidence`
(mean competition-evidence confidence), `research_completeness` (mean of
the four coverage metrics), `unknown_ratio` (mean opportunity-score
`unknown_pct`, defaulting to `1.0` — fully unknown — when candidates
haven't been scored at all yet), and `research_freshness` (fraction of
competition evidence observed within `freshness_window_s` of `now`).
Empty input yields all-zero coverage, never a fabricated default.

## Research Portfolio

`build_research_portfolio()` buckets every candidate into exactly one of
six mutually-exclusive buckets, evaluated in this priority order:

1. **`high_uncertainty_opportunities`** — confidence < 0.3, or unscored.
2. **`top_opportunities`** — composite score ≥ 60 and confidence ≥ 0.6.
3. **`undervalued_opportunities`** — a strong observed `supplier_advantage`
   (≥ 0.4) grounded in real margin evidence, even though the composite
   score alone doesn't yet clear the top-bucket bar.
4. **`high_risk_opportunities`** — the score has real, non-empty `risks`.
5. **`emerging_opportunities`** — composite score ≥ 50.
6. **`rejected_candidates`** — everything else.

`top_candidate_id` prefers a genuine `top_opportunities` pick, but falls
back through `undervalued -> high_risk -> emerging` (never
`high_uncertainty`/`rejected`, which are explicitly "do not advance yet")
so a portfolio without a confidently-top candidate can still hand Commerce
MVP a usable, honestly-reasoned selection — or `None` when nothing in any
advanceable bucket exists.

## Opportunity Evolution

This module is stateless: `compare_portfolios(previous, current)`
deterministically diffs two already-built `ResearchPortfolio` objects
(the caller supplies both — no hidden database or persistence layer is
introduced). For each candidate: `score_delta`, `confidence_delta`,
`rank_delta` (position change within `top_opportunities`, when present on
both sides), and `change_kind` (`"new"`/`"removed"`/`"improved"`/
`"declined"`/`"unchanged"`). The CLI (see below) demonstrates a real,
lossless round-trip: a prior run's `--json` output can be fed back in via
`--previous-portfolio-json` to compute real movement — reconstructing a
comparable `ResearchPortfolio` from `portfolio.to_dict()`'s own output,
not from the (deliberately lossy) decoded read-API summary.

## Commerce MVP integration

`run_commerce_mvp_slice(..., research_portfolio=None)` is an additive,
`None`-default parameter. With the default, this capability is never
consulted — byte-identical to the pre-existing behavior. When supplied and
its `top_candidate_id` matches one of the run's candidates, **it takes
priority over both the default single-candidate pick and
`use_opportunity_ranking`** — "Commerce MVP should consume the Research
Portfolio instead of isolated candidates when available." An unmatched
`top_candidate_id` (e.g. `None`, or a candidate not present in this run)
falls back to the existing default selection, never raises.

`ResearchPortfolio`/`PortfolioBucketEntry` carry score *summaries*, not raw
supplier/competition evidence objects (keeping the JSON payload bounded);
economics grounding still comes from the existing `supplier_evidence`/
`competition_evidence` parameters — the caller who built the portfolio is
expected to pass the same evidence it used for that top candidate. This
module never orchestrates evidence-gathering itself.

**Stated limitation**: `run_commerce_mvp_from_public_rss()` gained a
lightweight `research_portfolio` passthrough parameter, but does **not**
build a portfolio internally — automatic multi-candidate evidence
gathering inside the public-network path is out of scope this round (the
existing `attempt_supplier_evidence`/`attempt_competition_evidence` peek
logic only ever gathers evidence for one candidate). The real, working
multi-candidate path is `scripts/run_product_research_engine.py`
(`--gather-evidence`), which builds candidates, gathers evidence per
candidate, scores, and constructs a full portfolio — demonstrating the
complete vertical slice end-to-end.

## Canonical events

`product_research_events(portfolio, candidates, *, run_id, comparison=None)`
emits, reusing the existing `Event`/`EventRepository` system (own
event-type set, following the `opportunity_scoring_events()`/
`competition_intelligence_events()` precedent):

1. `candidate_discovered` — once per candidate.
2. `candidate_clustered` — once per cluster.
3. `research_portfolio_updated` — once, with bucket counts and quality.
4. `ranking_changed` — once per real movement (only when a `comparison` is
   supplied, and only for non-`"unchanged"` movements).
5. `research_completed` — once.

Emitted by whoever *built* the portfolio (mirroring
`opportunity_scoring_events()`/`competition_intelligence_events()`) —
`run_commerce_mvp_slice()` only *consumes* an already-built portfolio and
never re-emits these itself.

## Read API and dashboard view

Two read routes, following the exact `query_service.py` pattern already
established:

- `GET /api/events/product-research` — thin `event_type` filter over the
  generic timeline.
- `GET /api/events/research-portfolio` — decoded summaries via
  `build_research_portfolio_summaries()`, carrying candidate/cluster
  counts, bucket counts, quality metrics, cluster membership, and
  movements.

While adding these, a **pre-existing bug** was found and fixed:
`api/routes/canonical_events.py::_jsonl_report()`'s unconfigured-JSONL-path
fallback dict was missing the `opportunity_rankings`/`competition_summaries`
keys added by the two prior Phase 1 sessions, which meant
`/api/events/opportunity-rankings` and `/api/events/competition-summaries`
raised a raw `KeyError` (not even a clean 4xx) whenever
`MARKETOS_EVENT_READ_JSONL_PATH` was unset. Fixed alongside adding
`research_portfolios` to the same fallback dict, with a regression test
(`tests/integration/test_research_portfolio_read_api.py::test_unconfigured_jsonl_path_never_key_errors_on_any_summary_route`).

The **Research portfolio** tab in `/operator/events` reads
`/api/events/research-portfolio` and renders: bucket counts, research
quality metrics, top movers (from the most recent comparison, when
present), and an expandable cluster list (name, member count, confidence,
price range, supplier/competition diversity).

## CLI

`scripts/run_product_research_engine.py --fixture <path> --json` (or
`--public-query "..."` for the public RSS path) builds a full portfolio.
`--gather-evidence --allow-network` attempts real supplier + competitor
evidence per candidate (bounded by `--max-candidates`); without
`--allow-network` evidence gathering is dry-run/simulated. `--markdown`
prints the portfolio bucket report; `--markdown --clusters` prints the
cluster report instead. `--previous-portfolio-json <path>` computes real
ranking movement against a prior run's own `--json` output. `--write-jsonl`
writes canonical events. No provider mutation in any mode.

## Real validation

Live evidence collection (via `--gather-evidence --allow-network`) was
attempted from this development sandbox and is blocked identically to
every other live-evidence path documented in this Phase 1 work
(`docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md`, `docs/COMPETITION_INTELLIGENCE.md`)
— the sandbox's outbound-HTTPS proxy rejects the `CONNECT` at the gateway
level for every domain outside its explicit allowlist. The dry-run path
was exercised end-to-end (fixture signals -> candidates -> identity
resolution -> clustering -> quality -> portfolio -> events -> JSONL
write), confirming honest degradation rather than fabricated evidence.
Identity resolution/clustering/portfolio math itself needs no network
access and is fully covered by fixture-based tests.

## Testing

- `tests/test_product_research.py` — normalization, identity resolution,
  duplicate/variant grouping (including "never merges below threshold"),
  clustering (including the category-tag naming regression guard above),
  research quality (coverage, freshness, unknown-ratio), portfolio
  bucketing (every candidate in exactly one bucket, deterministic,
  empty-input), portfolio comparison (new/removed/improved/unchanged),
  canonical events (types, advisory metadata, correlation, determinism),
  candidate aggregation.
- `tests/integration/test_product_research_commerce_mvp.py` — the
  `research_portfolio` runner param: byte-identical default, top-pick
  selection, priority over `use_opportunity_ranking`, economics grounding,
  unmatched-id fallback, deterministic replay.
- `tests/contracts/test_research_portfolio_summaries.py` —
  `build_research_portfolio_summaries()`: decoded data, unrelated-event
  exclusion, `event_query_report()` wiring.
- `tests/integration/test_research_portfolio_read_api.py` — both read
  routes plus the `_jsonl_report()` regression guard above.
- `tests/integration/test_run_product_research_engine_script.py` — the
  CLI: fixture mode, JSON/Markdown/cluster-report output, mutually
  exclusive flags, explicit JSONL write, deterministic bucket placement,
  and the previous-portfolio-JSON comparison round-trip.

No existing test was modified to reduce coverage.

## Future extensions

- Automatic multi-candidate evidence gathering inside
  `run_commerce_mvp_from_public_rss()` — stated limitation above; needs a
  design decision on bounding total network calls (N candidates × 2
  evidence sources) before it belongs in the gated public-network path.
- Persisting portfolios (beyond JSONL replay) to make
  `--previous-portfolio-json`-style comparison automatic across scheduled
  runs, once there's a real need for it beyond manual operator comparison.
- Feeding `ResearchCandidate.additional_evidence` from Shopify read-only
  context (`backend.ecommerce.shopify_readonly`) — the field exists for
  exactly this, not yet wired.
