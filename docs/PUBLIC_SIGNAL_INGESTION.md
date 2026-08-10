# Public Signal Ingestion Pilot

This pilot is the evidence entry point for the narrow, deployable
[MVP Island](MVP_ISLAND.md). It stays manually invoked and advisory even when
a future caller persists its canonical events with the optional Supabase
repository adapter.

## Purpose

This pilot ingests bounded, public/no-credential RSS observations and appends canonical `public_signal_observed` events only when an operator explicitly requests a JSONL output. It is a useful evidence-acquisition path, not a commerce execution, launch, advertising, or financial decision path.

## Chosen source

The pilot uses the public Google News RSS search endpoint:

```text
https://news.google.com/rss/search?q={url_encoded_query}&hl=en-US&gl=US&ceid=US:en
```

It is a public RSS response read with a single bounded HTTP GET, fixed User-Agent, eight-second timeout, one-megabyte response guard, and maximum 25 records. It uses no credentials, login, cookie, browser automation, CAPTCHA handling, pagination, paid API, or provider mutation.

Network access is not automatic: the CLI requires `--allow-network`. Fixture mode is deterministic and has no network dependency. A failed approved network read serves an existing local cache as `stale_cache`; without cache it returns a structured degraded result instead of raising.

## What a signal contains

`PublicSignal` preserves a stable content-derived ID, source and evidence URLs, source publication timestamp, query, title, description, source-local rank/score, tags, publisher attribution, raw excerpt/reference, quality limitations, and dry-run/advisory markers.

Scores are source-local rank values. A public RSS observation cannot prove demand, market size, profitability, ROAS, conversion, product quality, supplier viability, investment value, or launch readiness. Downstream systems must treat it as advisory evidence requiring corroboration.

## Canonical event mapping

Each explicitly written signal becomes a canonical `Event`:

- `aggregate_type`: `public_signal`
- `event_type`: `public_signal_observed`
- `aggregate_id`: signal ID
- `payload`: normalized `PublicSignal`
- metadata: `dry_run`, `advisory`, `no_credentials`, `public_source`, `non_authoritative`, `no_launch_authority`, `no_spend_authority`, cache status, and source URL.

Only an explicitly supplied `JsonlEventRepository` receives events. The pilot does not write legacy workflow JSONL, change an existing source adapter, or schedule ingestion. Canonical events are replay-certified through the existing EventRepository/replay utilities.

## CLI

```powershell
# Deterministic, no-network preview
python scripts/ingest_public_signals.py --fixtures --json

# Explicit canonical JSONL write from fixtures
python scripts/ingest_public_signals.py --fixtures --write-jsonl artifacts/public-signals.jsonl --json

# Explicit, manually invoked public read
python scripts/ingest_public_signals.py --source rss --query "ecommerce trends" --limit 5 --allow-network --json
```

Without `--allow-network`, non-fixture invocation returns a clear blocked report or a local stale-cache result. `--write-jsonl` is the only event-write option and creates canonical advisory events; it cannot launch, spend, publish, order, pay, or mutate external systems.

## Source readiness

`public_rss_readiness()` reports `requires_credentials: false`, `configured: true`, cache availability, last success, `allowed_actions: [read_public_only]`, and forbidden actions: write, publish, spend, mutate, login, and credentialed fetch. It is a lightweight source-specific report rather than a second readiness framework.

`PublicSourcePolicy` and `validate_public_ingestion_request()` make that boundary executable: only RSS is accepted, queries are normalized, limits above 25 are rejected rather than silently expanded, fixture mode needs no network, and real reads require an explicit network opt-in. `public_source_capabilities()` exposes a small readiness-compatible capability payload without changing the existing research readiness/flag framework.

## Batch audit and replay certificate

Every CLI result includes a deterministic advisory audit: signal and unique-ID counts, publisher/source-URL coverage, evidence limitations, canonical envelope validation, authority violations, stable replay hashes, and next actions. The audit is constructed even for preview mode; writing JSONL is unnecessary to verify the candidate canonical events.

An audit failure is a data/provenance blocker, not an execution failure that triggers a retry or a change in downstream behavior. In particular, missing non-authoritative metadata, aggregate/payload mismatch, or any live-authority marker prevents an advisory-only certificate.

## Adding another public source

The existing Google News RSS adapter is also composed by the Commerce MVP
public-run mode. That path keeps the same explicit network gate, cache/stale
fallback, record limit, and advisory canonical event metadata.

Add one source at a time with an allowlisted endpoint, explicit operator network gate, bounded timeout/size/record limits, fixtures, deterministic normalization, cache/stale behavior, source attribution, canonical event mapping, replay certification, and no-authority metadata. Do not add credentialed, browser-driven, paid, access-controlled, or mutation-capable sources to this pilot package.

## Deferred work

Reddit is already represented by a legacy public adapter, but it is deferred here because its existing direct fetch path lacks this pilot’s explicit CLI network gate and canonical mapping. Google Trends/pytrends is deferred because it relies on an unofficial dependency. TikTok, Meta, Shopify, suppliers, payments, provider APIs, and browser automation remain out of scope.

## Operational limits

The RSS endpoint is queried once per manual invocation; there is no scheduler, cursor, retry loop, or pagination. A successful response is cached only after normalization yields signals. Cache data is local observation data, not a source of truth, and stale cache use is surfaced in the ingestion result and canonical metadata.

Do not put source-derived text into claims, testimonials, product listings, campaign copy, or messages without independent review. News headlines can be incomplete, duplicated, syndicated, regional, or unrelated to purchase intent. The pilot stores enough attribution to inspect the underlying link and requires downstream users to preserve those limitations.

When the source is inaccessible, rate limited, changes its feed shape, or returns no usable items, the correct result is a structured `degraded`/`blocked` observation or a marked stale cache—not browser fallback, proxy rotation, credential use, automatic retries, or an attempt to bypass access controls.

## Review checklist for a real read

Before manually passing `--allow-network`, confirm that the query is relevant and non-sensitive, the small record limit is sufficient, the endpoint remains public/no-auth, and the result will be treated as advisory. After a read, inspect source URLs, publisher attribution, warnings, cache status, and the batch audit before using any observation in research.

If these conditions are not met, use fixture mode or local imports instead. The appropriate response to uncertainty is less automation and more provenance—not a wider connector surface.

## Retention and privacy

The pilot keeps only the normalized title, description excerpt, publisher attribution, evidence URL, and source timestamp required for research provenance. It does not request user profiles, account data, cookies, messages, or personalized feeds. Operators should continue to avoid queries containing personal, confidential, or customer-identifying information.

Caches are local convenience snapshots. They may be removed at any time without affecting legacy systems, workflow JSONL, provider state, or any business decision. A missing cache simply yields a blocked/degraded observation until an operator chooses fixture mode or an explicitly authorized public read.
