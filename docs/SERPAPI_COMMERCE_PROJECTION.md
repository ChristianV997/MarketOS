# SerpApi commerce projection (v1)

A thin, deterministic, offline downstream consumer of the existing SerpApi
runtime adapter (`backend/adapters/research/serpapi.py`, merged in PR
#219), reshaping its already-normalized evidence into a commerce-facing
projection report. This is not a second adapter, not a second provider
registry, and not a new evidence engine.

## Why this exists

The SerpApi adapter returns normalized, sanitized evidence records, but a
consumer still has to decide how those records relate to MarketOS's
existing commerce concepts (marketplace evidence, in particular) without
guessing or duplicating logic. This module makes those decisions once,
explicitly and conservatively, so a future caller does not have to
reinvent them.

## What this deliberately does *not* do

- **Not a fourth Product Opportunity Synthesis pillar.**
  `evaluation/commerce/opportunity_synthesis.py` fuses exactly three
  offline evidence pillars (marketplace, supplier, consumer). This module
  is not wired into it, is not imported by it, and does not add a
  parameter there.
- **Never converts SERP titles into Consumer Attention evidence.**
  `evaluation/commerce/consumer_attention.py`'s evidence model is
  untouched and unimported here — confirmed by a static AST-based test.
- **Never infers a marketplace from generic Google-Shopping-shaped
  results.** A `MarketplaceTrendEvidence` projection
  (`evaluation/commerce/marketplace_trends.py`, an existing, unmodified
  module) is constructed only when the *caller* names a marketplace
  explicitly, and only when that name is a member of that module's own
  existing `SUPPORTED` set (`amazon`, `ebay`, `mercadolibre`, `alibaba`,
  `aliexpress`, `etsy`, `walmart`, `shopify`, `woocommerce`). No SerpApi
  field is ever inspected to guess a marketplace name; an unsupported or
  unnamed marketplace always yields `marketplace: null,
  marketplace_evidence: null`.
- **Never double-counts with DataForSEO.** This module does not import
  `backend.adapters.research.dataforseo` or
  `evaluation.commerce.dataforseo_adapter` anywhere — confirmed by a
  static AST-based test — so there is no code path that could combine or
  sum the two. Every report explicitly states, in both JSON
  (`non_double_counting_note`) and Markdown output, that SerpApi and
  DataForSEO are consolidation-choice alternatives for the same
  `search_serp_data` capability, not independent confirmations.
- **No launch, advertising, publishing, ordering, payment, or
  provider-mutation authority.** The `safety_summary` on every report
  structurally cannot be constructed with any of those set `True`.

## Dry-run-only status

The adapter is always invoked with a `SidecarContext(dry_run=True)`
constructed internally — this module exposes no CLI flag or parameter to
request a live call. `backend.adapters.research.serpapi.fetch_search_evidence`
remains the sole owner of live/dry-run behavior.

## Fixture identity labelling

Every projected record carries `fixture_identity_label:
"synthetic_fixture_example"` and `evidence_tier: "supplemental_non_live"`
— unambiguous, explicit markers that no field in the record is live search
proof.

## Rejection behavior

- An oversized `query` (over `MAX_QUERY_LENGTH` = 200 characters) is
  rejected with `ValueError` before it ever reaches the adapter.
- A secret-shaped or raw-HTML-shaped `fixture_payload` is rejected with
  `ValueError` by this module's own guard, *before* it ever reaches the
  adapter — defense in depth on top of the adapter's own equivalent
  guard.
- An oversized `fixture_payload` is rejected with `ValueError` before it
  ever reaches the adapter — bounded by both serialized byte size
  (`MAX_FIXTURE_PAYLOAD_BYTES` = 65,536 bytes) and record count
  (`MAX_FIXTURE_RECORDS` = 100). Neither the adapter nor this module's own
  secret-shape scan previously capped fixture size at all — a caller could
  have passed thousands of records or a multi-megabyte payload and it
  would have been processed in full; this is now rejected outright rather
  than silently truncated.
- A payload that is malformed at the adapter's own contract level (e.g.
  `records` not a list) is *not* re-validated here — it fails closed via
  the adapter's existing `status="error"` path, which this module passes
  through unchanged (`record_count=0`).
- An empty (but syntactically valid) `records` list is treated as a
  legitimate zero-signal result, not an error.

## Future activation requirements

Identical to the underlying SerpApi adapter's own prerequisite list — this
module adds no new provider, so it adds no new activation gate.

## CLI

```
python scripts/run_serpapi_commerce_projection.py --json
python scripts/run_serpapi_commerce_projection.py --markdown
python scripts/run_serpapi_commerce_projection.py --query "insulated travel mug" --marketplace amazon --json
python scripts/run_serpapi_commerce_projection.py --fixture tests/fixtures/serpapi_commerce_projection/serpapi_shopping_sample_dry_run.json --json
python scripts/run_serpapi_commerce_projection.py --output artifacts/serpapi_commerce_projection/latest --markdown
```

Default behavior (no `--output`) never writes a file. `--output` writes
exactly three files (JSON report, Markdown report, records-only JSON) —
generated artifacts are not committed to this repository.

## Determinism

`generated_at` defaults to the deterministic sentinel string
`"offline-deterministic"` (matching `build_dataforseo_adapter_report`'s
and `build_intelligence_adapter_plan`'s own convention) — never a real
wall-clock timestamp — so two calls with identical inputs always produce
byte-identical JSON/Markdown output.

## Safety boundaries

No network, credential, model, provider, SDK, or plugin call occurs
anywhere in this module or its CLI (verified by an AST-based import
denylist test). No artifact is written unless `--output` is explicitly
supplied. No raw provider payload or HTML is ever stored — every projected
field is already-normalized, whitelisted data the adapter itself produced.
