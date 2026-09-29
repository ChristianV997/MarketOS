# Offline Consumer Attention and Creative Evidence

MarketOS now has a deterministic, offline-first layer for answering a question
that demand and supplier evidence cannot answer: can a product be explained,
demonstrated, and marketed clearly enough to deserve creative testing?

This is a research layer for consulting reports. It is not an ad launcher, a
posting tool, an audience-targeting system, or supplier proof.

The authority is product-agnostic: an evidence row may describe `goods`,
`service`, `hybrid`, or explicitly `unknown` offering kinds. The model does not
infer the offering kind from a candidate label.

## What it measures

The model accepts sanitized snapshots and manual imports from Google Trends,
TikTok Creative Center and ad snapshots, Meta Ad Library, YouTube, Reddit,
Amazon/Mercado Libre/eBay/Shopify reviews, and Minea, Dropship.io, Pipiads,
and Kalodata manual imports. Every record carries a source type, platform,
field-level provenance, confidence, and the mandatory `read_only`,
`network_calls`, and `mutated` safety flags. Optional observation metadata is
validated and retained: timezone-aware `observed_at`, `offering_kind`,
geography, language, an observation key, and an observation value. Missing
observation time remains unavailable; it is never replaced with a generated
timestamp.

## Run it

```powershell
python scripts/run_consumer_attention_intelligence.py --json
python scripts/run_consumer_attention_intelligence.py --markdown
python scripts/run_consumer_attention_intelligence.py `
  --manual-import tests/fixtures/consumer_attention/reddit_comments_manual_import.csv `
  --json
python scripts/run_consumer_attention_intelligence.py `
  --output artifacts/consumer_attention/latest `
  --markdown
python scripts/run_consumer_attention_intelligence.py `
  --candidate-seed tests/fixtures/consumer_attention/service_market_generic.json `
  --as-of 2026-09-10T00:00:00Z `
  --json
```

The default path performs no network calls and writes no files. With
`--output`, only the sanitized report, source summary, and creative-angle
summary are written. Inputs are local JSON/CSV; traversal paths, unsupported
extensions, secret-like fields, raw HTML/provider-payload fields, and malformed
rows are rejected or skipped.
Use `--as-of` to classify rows as `fresh`, `stale`, `future_dated`, or
`unavailable`. The CLI never consults the host clock, so replay and review are
deterministic. Without an explicit reference time, freshness is
`unavailable`. The default freshness window is 90 days and can be changed with
`--freshness-days` for a documented review.

## Scoring and creative extraction

The deterministic scorer combines search/trend growth, social engagement, ad
activity, review density, voice-of-customer quality, pain-point clarity,
objection density, hook diversity, UGC scriptability, visual demonstration
potential, intent, source diversity, and attention saturation risk. It returns
contributions and an explicit recommendation such as `validate_supplier_first`,
`generate_creative_tests`, `expand_consumer_research`, `reject_low_attention`,
or `reject_high_objection_risk`.

Creative extraction is transparent rather than generative. It deduplicates
hooks, surfaces pain points, desired outcomes, objections, claims, and proof
signals, then maps words to bounded angle categories such as
`problem_solution`, `demo`, `comparison`, `convenience`, `cost_saving`,
`health_wellness`, and `travel_portability`. UGC and landing-page hints are
hypotheses for human review, not approved ad copy.

## How it fits the report

Pass it into the existing Product Validation Report alongside marketplace and
supplier evidence:

```powershell
python scripts/generate_product_validation_report.py `
  --marketplace-trend-report artifacts/marketplace_trends/latest/marketplace_trend_report.json `
  --supplier-feasibility-report artifacts/supplier_feasibility/latest/supplier_feasibility_report.json `
  --consumer-attention-report artifacts/consumer_attention/latest/consumer_attention_report.json `
  --markdown
```

The report adds attention signals, search/trend signals, ad/creative evidence,
voice-of-customer themes, objections, hooks, UGC angles, and source confidence.
If the input is absent, it says `consumer_attention_not_supplied` rather than
inventing a conclusion. Opportunity synthesis remains a thin join over the
three existing reports.

## Source roles and limitations

Google Trends contributes directional search movement, not sales. TikTok and
Meta snapshots contribute creative/ad activity, not campaign performance.
YouTube and Reddit contribute language and objections, not representative
market demand. Reviews contribute voice-of-customer themes, not verified
causal claims. Minea, Dropship.io, Pipiads, and Kalodata are manual inputs in
this slice, not connected dashboards.

Consumer attention is separate from marketplace demand and supplier
feasibility. A compelling hook does not prove stock, shipping, authorization,
profitability, or launch readiness. A recommendation to generate creative
tests is not permission to spend money or publish content.

If two sources report different values for the same `observation_key` for a
candidate, the report emits `conflicting_consumer_observations`, blocks that
candidate's attention recommendation, and asks the operator to resolve the
conflict. Equal values from different sources do not create a conflict. This
is a quality control on attention evidence, not a supplier, compliance, or
economic decision.

The checked-in service-market fixture is intentionally generic:
`tests/fixtures/consumer_attention/service_market_generic.json`. It exercises
service and hybrid offering metadata without naming a commercial product.
It is fixture evidence only. It cannot prove demand, supplier availability,
legal clearance, pricing, delivery capacity, customer identity, or launch
readiness.

## Safety boundary

This layer never logs into platforms, calls social/ad APIs, scrapes paid
dashboards, bypasses CAPTCHA/robots controls, stores raw HTML or raw social/ad
payloads, posts content, launches ads, sends messages, mutates Shopify, places
orders, or changes provider state. No credentials belong in fixtures,
Markdown, JSON, or Git.

Product Opportunity Synthesis uses this layer for hooks, pain points,
objections, attention confidence, and creative-test prioritization. It does not
turn consumer interest into supplier proof or launch authorization.

The downstream contract is deliberately fail-closed: attention-only input
keeps supplier feasibility unavailable, leaves economics empty, and routes
Product Validation and Opportunity Synthesis to supplier validation. Existing
Launch Draft and Site Draft consumers may produce bounded draft payloads, but
their approval and publishing flags remain false and platform payloads remain
`status: draft`. An explicit supplier-proof input is an upstream contract; it
is not inferred from attention rows and is not created by this module.

## Acceptance checks

```powershell
python -m pytest -q tests/test_consumer_attention.py tests/test_consumer_attention_cli.py tests/test_consumer_attention_contract.py tests/test_consumer_attention_downstream_integration.py tests/test_consumer_attention_negative_controls.py
python -m pytest -q tests/test_product_validation_report.py tests/test_product_opportunity_synthesis.py tests/test_launch_draft_pack.py tests/test_site_draft_builder.py
python scripts/run_consumer_attention_intelligence.py --candidate-seed tests/fixtures/consumer_attention/service_market_generic.json --as-of 2026-09-10T00:00:00Z --json
```

These checks are local fixture/dry-run evidence. They do not activate
providers, call networks, spend money, publish content, place orders, or
constitute live commercial validation.
