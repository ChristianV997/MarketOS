# Competition Intelligence

`backend/adapters/research/competition_evidence.py` (evidence source) and
`backend/mvp_commerce/competition_intelligence.py` (aggregation) are the
missing intelligence layer between Supplier Evidence and Opportunity
Scoring:

```text
Public Signals -> Supplier Evidence -> Competition Intelligence ->
Opportunity Scoring -> Commerce MVP -> Canonical Events -> Operator Dashboard
```

They answer questions the repository could not answer before: is a market
saturated, how many competitors are actually selling a product, what price
is really being charged, and is an estimated margin grounded in observed
competitor prices rather than an assumption.

## Repository audit and reuse decisions

Before writing any extraction code, the existing codebase was searched for
JSON-LD/schema.org parsing, HTML scraping, and competition-related logic.
Findings that shaped this design:

- **`backend.adapters.research.crawl4ai.Crawl4AIResearchAdapter._product_records_from_jsonld`**
  is the repository's one canonical schema.org `Product` JSON-LD parser,
  already reused by `cj_public_evidence.py`. This module reuses it too
  (`competition_evidence._extract_from_jsonld`) rather than writing a
  second parser — and extends it **additively** (new `rating`,
  `review_count`, `seller`, `image`, `shipping_cost` dict keys) since
  competitor-listing comparison needs fields the original CJ-evidence path
  never did. Every pre-existing consumer of that static method (`bs4`/
  `lxml`-free callers included) is unaffected: no existing key was
  renamed, removed, or changed — confirmed by running the full pre-existing
  `crawl4ai`/`cj_public_evidence`/OSS-bridge test suites unchanged.
- **`cj_public_evidence.py`'s SSRF-safe fetch/robots/cache pattern** (DNS-
  rebinding-safe URL validation, `robots.txt` enforcement, bounded GET with
  no redirects and a size cap, in-process TTL cache) is reused structurally
  in `competition_evidence.py`, but **without** `cj_public_evidence`'s
  fixed `ALLOWED_HOSTS` allowlist — a competitor listing can be on any
  public storefront domain an operator supplies, unlike CJ's one fixed
  supplier host. SSRF protection itself (private/loopback/link-local/
  reserved/multicast rejection) is unconditional and never relaxed.
- **`backend.discovery.ad_intelligence.competition_summary()`** already
  computes ad-based `market_saturation`/`competitor_count` from the Meta Ad
  Library. That is a different signal (ad presence, not product listings)
  and is left untouched; this module's `market_saturation` dimension is
  independently sourced from observed listing counts, with its own
  `SATURATION_CEILING` constant (never conflated with
  `ADLIB_SATURATION_CEILING`).
- **`backend/commercial_intelligence/`** already has `competition_score`/
  `saturation_score` fields end-to-end (`market_analyzer.py`,
  `product_analyzer.py`, `scoring.py`), fed from *locally recorded*
  `discovery_registry` evidence rather than live competitor scraping.
  `ARCHITECTURE_CONTRACT.md` asks new work to "reuse a canonical owner or
  document an approved exception" — this is that documented exception,
  for the same reason `opportunity_scoring.py` itself isn't named "Product
  Intelligence" (see that module's docstring): `commercial_intelligence/`
  is one of the heavier, "OFF in the MVP Island" experimental modules
  (`docs/MVP_ISLAND.md`) the Commerce MVP vertical slice deliberately does
  not depend on. Wiring live competitor evidence into `discovery_registry`
  would widen that dependency surface for no benefit to this slice.
- **OSS libraries evaluated, not adopted**: `extruct` (schema.org/JSON-LD
  extraction), `price-parser` (free-text price string parsing), `w3lib`.
  None are installed in this environment, none are declared in
  `requirements.txt`/`requirements-oss.txt`, and this module never needs
  to parse a free-text price string — every extracted price already comes
  from JSON-LD's numeric `offers.price`/`offers.lowPrice` field (via the
  shared parser), so `price-parser` solves a problem this module doesn't
  have. `extruct` would duplicate, not improve on, the already-working
  `_product_records_from_jsonld`. Adopting either would add a new
  dependency for capability the repository already has; rejected as
  unnecessary rather than evaluated-and-inferior.
- **`backend/adapters/alibaba_trends.py`**'s established precedent for
  JS-heavy storefronts (plain `requests`/`bs4` scraping is infeasible
  against Cloudflare/JS-challenge pages; the repo's answer there is
  optional Firecrawl, with a mock fallback) applies here too: this module
  makes no claim to defeat JS-rendered storefronts by default. After the
  Phase 1 live harness reached public storefronts but static extraction
  returned no Product records, this adapter gained the same explicit,
  bounded Crawl4AI fallback as supplier evidence. It requires
  `MARKETOS_PHASE1_JS_RENDER=1` plus `CRAWL4AI_ALLOWED_DOMAINS`, preserves
  robots enforcement, and yields an honest, fully-`"missing"` degraded
  result if the optional dependency or structured output is unavailable.

## Competition Evidence

`backend/adapters/research/competition_evidence.py` is read-only, public-
page-only, no credentials, no authentication, no provider mutation, no
browser automation. `fetch_competitor_offer(url, *, source="", context)`
never raises; it degrades to a fully-`"missing"` `CompetitorOffer` on any
rejection, robots-disallow, network failure, or missing structured data.

`CompetitorOffer` fields: `title`, `price`, `currency`, `availability`,
`shipping_cost`, `brand`, `seller`, `rating`, `review_count`,
`variant_count`, `image`, `source_url`, `crawl_timestamp`, `confidence`,
`source`, `warnings`, and a `field_status` dict pairing every field with
one of `FIELD_STATUSES = ("observed", "derived", "assumed", "missing",
"malformed", "stale")`. `variant_count` is **always** `"missing"`: no
general schema.org `Product` signal reliably exposes variant count for a
single listing page, and this module never guesses it.

### Supported sources

No fixed host allowlist — an operator supplies any public listing URL
(Google Shopping, Amazon, Etsy, AliExpress, manufacturer pages, Shopify/
WooCommerce storefronts, or any other public product page).
`KNOWN_SOURCE_LABELS` maps a handful of well-known hostnames to a readable
`source` label (`"amazon"`, `"etsy"`, `"aliexpress"`, ...); anything else
is labeled `"public_storefront"`. Adding a new source is adding a hostname
label — the extraction/scoring/aggregation code below never changes per
source, by design.

No automatic per-source discovery (Google Shopping search, Amazon search
results, etc.) is implemented this round — the reliable path is operator-
supplied `competitor_urls`, matching `cj_public_evidence.py`'s own
precedent ("operator-supplied product URLs remain the reliable Phase 1
path; discovery is best-effort/unverified"). See "Future extensions" below.

## Market Intelligence

`backend.mvp_commerce.competition_intelligence.gather_market_intelligence(query, *, context, competitor_urls, max_competitors=10)`
fetches each supplied URL and aggregates only what was actually observed
into a `MarketIntelligenceReport`:

| Field | Computed from |
|---|---|
| `observed_competitor_count` | count of offers with an *observed* price |
| `observed_median_price`/`mean`/`min`/`max` | `statistics` over observed prices |
| `observed_pricing_variance` | population stdev of observed prices |
| `observed_shipping_min`/`max` | observed `shipping_cost` values |
| `observed_review_density` | mean `review_count` among offers reporting one |
| `observed_rating_mean` | mean `rating` among offers reporting one |
| `observed_brand_diversity`/`observed_seller_diversity` | distinct brands/sellers ÷ total offers |
| `observed_availability_ratio` | in-stock offers ÷ offers that reported availability at all |
| `market_saturation` | `min(1.0, observed_competitor_count / SATURATION_CEILING)` |
| `market_maturity` | `"unknown"` with no review/rating signal; `"established"` above a review-density/rating threshold; else `"emerging"` |
| `confidence` | fraction of the 8 aggregate dimensions that are non-empty |

Never raises; with zero `competitor_urls` it returns a fully-honest empty
report (`observed_competitor_count=0`, all pricing fields `None`) with a
`"no_competitor_urls"` warning, never fabricated numbers.

## Margin Intelligence

`compute_margin_intelligence(candidate_id, *, supplier_evidence, market_report)`
combines an observed supplier unit cost (`SupplierEvidenceResult`, from
`backend.mvp_commerce.supplier_evidence`) with observed market prices:

- `observed_gross_margin = (median_price - unit_cost) / median_price`
- `observed_margin_low`/`observed_margin_high` use the observed min/max
  market price instead of the median.
- `observed_supplier_advantage = (min_price - unit_cost) / min_price` —
  the supplier's cost edge versus the cheapest observed competitor.
- `observed_margin_confidence` blends market confidence with whether a
  supplier cost was actually observed.

Either input missing → the corresponding outputs are `None`, with an
explicit warning (`"no_observed_supplier_cost"`/`"no_observed_market_price"`)
— never filled in with an assumption.

## Opportunity Scoring integration

`backend/mvp_commerce/opportunity_scoring.py` was **extended**, not
replaced: `score_opportunity()`/`rank_opportunities()` gained additive
`competition_evidence`/`margin` (and `competition_evidence_by_candidate`/
`margin_by_candidate` on the ranking function) parameters, `None` by
default. Six new dimensions were added to `_all_dimensions()` — always
computed, resolving to `provenance="unavailable"` when no competition/
margin evidence is supplied, the exact same pattern the supplier-evidence
dimensions (`supplier_evidence_quality`, `product_simplicity`, ...) already
use:

| Dimension | Source | Weight |
|---|---|---|
| `market_saturation` | `MarketIntelligenceReport.market_saturation` (inverted: low saturation scores high) | 10.0 |
| `price_competitiveness` | observed price dispersion (`variance / median`) — market headroom, not a judgment on any specific assumed price | 10.0 |
| `supplier_advantage` | `MarginIntelligence.observed_supplier_advantage` | 10.0 |
| `market_confidence` | `MarketIntelligenceReport.confidence` | 5.0 |
| `review_strength` | blend of observed rating mean and review density | 5.0 |
| `offer_diversity` | mean of observed brand/seller diversity (consolidates the brief's separate "Offer Diversity"/"Brand Concentration"/"Seller Concentration" into one dimension — the underlying ratios remain individually visible on `MarketIntelligenceReport` for drill-down) | 5.0 |

This replaces the old permanently-`unavailable` `competition_estimate`
placeholder dimension. `category_stability` remains permanently
unavailable — Competition Intelligence observes pricing/saturation, not
category-level stability, and no data source for that exists in this
repository. Adding these dimensions changed the total dimension count from
14 to 19 for every score, and correspondingly lowered the reachable
confidence floor without any evidence from ~0.32 to ~0.24 — this is a
correctness improvement (more of the picture is now honestly represented
as unknown when it hasn't been gathered), not a regression; the existing
test suite was updated to reflect the new floor rather than papered over.

## Market Opportunity Report

`build_market_opportunity_report(candidate_id, product_name, *, opportunity_score=None, supplier_evidence=None, market_report=None, margin=None)`
is the operator-facing commercial decision artifact the task brief asked
for: opportunity score/confidence, a supplier summary, a competition
summary, observed pricing, observed supplier cost, observed margin, and
explicit `market_risks`/`strengths`/`weaknesses`/`missing_evidence`/
`operator_actions`/`recommended_next_step` — all derived purely from the
already-computed inputs (no new fetching, no new scoring math). It is
always built once `run_commerce_mvp_slice(..., use_opportunity_ranking=True)`
is used (mirroring the "always shown, never hidden" rule scoring
dimensions already follow) — without competition evidence it still reports
`missing_evidence: ["competitor_evidence"]` rather than omitting the
report.

## Commerce MVP integration

`run_commerce_mvp_slice(..., competition_evidence=None)` and
`run_commerce_mvp_from_public_rss(..., attempt_competition_evidence=False, competitor_urls=None)`
are additive, `None`/`False`-default parameters. With the default, this
capability is never consulted — byte-identical to the pre-existing
behavior (see `tests/integration/test_competition_intelligence_commerce_mvp.py::TestByteIdenticalDefault`).
`attempt_competition_evidence` only takes effect together with
`use_opportunity_ranking=True` — competition evidence composes through the
ranking path only, never the single-candidate default selection path,
matching the same "opt-in stacks on opt-in" discipline the supplier-
evidence integration already established.

When active: `CommerceMvpRun.metadata["market_opportunity_report"]` carries
the full report; `competition_intelligence_events()` are appended alongside
the existing `commerce_mvp_events()`/`opportunity_scoring_events()`.

## Canonical events

`competition_intelligence_events(market_report, margin, opportunity_report, *, workspace_id, run_id)`
emits, reusing the existing `Event`/`EventRepository` system (its own
event-type set, following the exact precedent `supplier_evidence_events()`/
`opportunity_scoring_events()` already set — not an extension of
`commerce_mvp_events()`'s `_EVENTS` tuple):

1. `competition_observed` — once per observed competitor listing.
2. `competition_summary_created` — once, the full `MarketIntelligenceReport`.
3. `market_pricing_computed` — once (when margin was computed), the full `MarginIntelligence`.
4. `market_intelligence_completed` — once (when a report was built), the full `MarketOpportunityReport`.

Event IDs are `"competition-intelligence-" + sha256(f"{run_id}:{suffix}")[:20]`
— deterministic replay.

## Read API and dashboard view

Two read routes, following the exact `query_service.py` pattern already
established for opportunity scoring:

- `GET /api/events/competition-evidence` — thin `event_type` filter over
  the generic timeline (fast, but redacted to `{"keys": [...], "item_count": N}`
  per the generic timeline's own privacy/bandwidth rule).
- `GET /api/events/competition-summaries` — decoded summaries via
  `backend.events.query_service.build_competition_summaries()`, carrying
  real observed pricing/saturation/offer/margin data. This is the route
  the dashboard reads.

The **Competition & pricing** tab in `/operator/events`
(`frontend/src/pages/OperatorEventDashboard.tsx`) reads
`/api/events/competition-summaries` and renders, per run: observed
competitor count, median price, saturation, maturity, confidence, a
supplier-vs-market margin card, and an expandable observed-price-
distribution table (title, source, price, brand, seller, rating, reviews,
per-offer confidence) — the evidence drill-down an operator needs to see
*why* a market looks the way it does. The **Run public Commerce MVP test**
form gained a **Gather public competitor pricing** checkbox and a
competitor-URL input, wired to `attempt_competition_evidence`/
`competitor_urls`.

## Deployment

`MARKETOS_COMPETITION_EVIDENCE_LIVE=1` server-side, plus
`attempt_competition_evidence: true` on the request, are both required for
a live fetch — the same double-gate pattern as
`MARKETOS_SUPPLIER_EVIDENCE_LIVE`. Without the server-side flag, the
request-level flag is silently ignored (never blocks the whole run), and
`competition_evidence_attempted: false` is reported honestly.

## CLI

`scripts/run_competition_intelligence_scan.py --query "..." --competitor-urls "url1,url2"` (or
`--competitor-urls-fixture path.json` for a fixture list) supports
`--allow-network` (otherwise dry-run/simulated), `--supplier-unit-cost`/
`--supplier-shipping-cost` for margin computation, `--json`/`--markdown`
output, and `--write-jsonl` for canonical event output. No provider
mutation in any mode.

## Real validation

A live fetch against real competitor storefronts (Google Shopping, Amazon,
Etsy, AliExpress, or an arbitrary manufacturer/Shopify/WooCommerce
domain) was attempted from this development sandbox and confirmed
**blocked identically to `cjdropshipping.com`** in the prior supplier-
evidence phase: the sandbox's outbound-HTTPS proxy rejects the `CONNECT`
at the gateway level (`403`, policy denial) for every domain outside its
explicit allowlist (PyPI, npm, Anthropic domains, private/internal
ranges) — confirmed against `www.google.com`, `shopping.google.com`,
`www.amazon.com`, `www.etsy.com`, `www.aliexpress.com`, `shopify.com`, and
`www.woocommerce.com` directly via `curl`, all returning the same
`CONNECT tunnel failed, response 403`. This is a sandbox network-egress
policy, not a site-side anti-bot response, and not specific to any one
competitor site. What remains genuinely unverified is whether real
competitor pages expose schema.org `Product` JSON-LD the way the fixture
HTML in this repository's tests assumes — that requires an environment
with real network access (Railway, or a local machine). The extraction/
aggregation/margin/scoring logic itself is fully covered by fixture-based
tests exercising the exact same code paths a live fetch would use; only
the live-network leg is unverified here.

## Testing

- `tests/test_competition_evidence.py` — URL/SSRF safety (no fixed host
  allowlist, still rejects private/loopback/link-local/reserved/multicast),
  dry-run gate, JSON-LD extraction (including the new rating/review/
  seller/shipping/image fields, never fabricates variant count), redirect/
  size-cap safety, caching, robots.txt enforcement, source labeling,
  competitor-listing comparison ranking, health.
- `tests/test_competition_intelligence.py` — market aggregation (only
  observed offers, honest degradation, saturation, determinism), margin
  computation (full/missing-supplier/missing-market/both-missing), market
  opportunity report (advance/gather-more/thin-margin-is-a-risk paths),
  canonical event emission (types, advisory metadata, correlation,
  determinism).
- `tests/test_opportunity_scoring.py::TestCompetitionDimensions` — all six
  new dimensions individually (unavailable without evidence, correct
  normalization, correct direction, per-candidate evidence keying in
  `rank_opportunities`).
- `tests/integration/test_competition_intelligence_commerce_mvp.py` — the
  `competition_evidence` runner param: byte-identical default (confirmed
  even with `competition_evidence` supplied but `use_opportunity_ranking`
  false), market-opportunity-report always-shown behavior, event emission,
  deterministic replay.
- `tests/integration/test_competition_intelligence_public_run.py` — the
  public-RSS-path opt-in, including the "only takes effect with
  use_opportunity_ranking=True" gating and the dry-run network guard.
- `tests/integration/test_commerce_mvp_public_run_api.py` — the API
  request field's server/request double-gate propagation (added cases
  only).
- `tests/integration/test_competition_evidence_read_api.py` — both read
  routes: filtering, rate limiting, route registration.
- `tests/contracts/test_competition_summaries.py` —
  `build_competition_summaries()`: decoded market/offer/margin data,
  unrelated-event exclusion, `event_query_report()` wiring.
- `tests/integration/test_run_competition_intelligence_scan_script.py` —
  the CLI: dry-run safety, JSON/Markdown output, mutually-exclusive flag
  validation, explicit JSONL write, margin computation.

No existing test was modified to reduce coverage; three pre-existing
`opportunity_scoring.py` tests were updated to reflect the new (larger,
more honest) dimension count and confidence floor, with the reasoning
documented inline at each change.

## Future extensions

- Automatic per-source discovery (search-results parsing for Google
  Shopping/Amazon/Etsy/AliExpress) — deliberately not built this round,
  matching `cj_public_evidence.py`'s own precedent; needs real-network
  verification of whether each source's search page exposes usable
  structured data or requires JS rendering (see "Real validation" above).
- `operator_actions`/`recommended_next_step` in `MarketOpportunityReport`
  currently use a small fixed heuristic; once there is real multi-run
  history, this could incorporate trend direction (is saturation/margin
  improving or worsening run over run) rather than a single snapshot.
- Firecrawl-based extraction for JS-heavy storefronts, following
  `alibaba_trends.py`'s precedent — only worth adding once a specific
  target source is confirmed to require it via real-network testing.
