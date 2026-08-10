# Public Commerce MVP Runs

MarketOS can run one operator-controlled Commerce MVP packet from the public
Google News RSS search feed. This is the first Phase 1 network behavior because
it is a bounded, no-auth, GET-only observation path. It does not prove demand,
sales, profitability, ROAS, supplier viability, conversion, or launch
readiness.

## CLI

Fixture mode remains the default and never performs a network request:

```powershell
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --query "portable espresso maker" --json
```

To perform a real public read, the operator must opt in explicitly:

```powershell
python scripts/run_commerce_mvp_slice.py --public-query "portable espresso maker" --allow-public-network --max-signals 10 --json
python scripts/run_commerce_mvp_slice.py --public-query "portable espresso maker" --allow-public-network --shopify-fixture tests/fixtures/shopify_readonly/shopify_sample.json --write-jsonl artifacts/commerce-mvp-live-events.jsonl --json
```

Without `--allow-public-network`, the result is `blocked` unless the existing
local cache can provide a marked `stale_cache` result. A failed fresh request
uses stale cache when available; otherwise it returns `degraded`. Successful
normalized results are `succeeded` and update the local cache.

## API and dashboard

The server endpoint is `POST /api/commerce-mvp/public-run`. It requires
`MARKETOS_PUBLIC_COMMERCE_RUNS=1` and accepts only the fixed
`google_news_rss` source. JSONL writes use the server-only
`MARKETOS_EVENT_WRITE_JSONL_PATH` beneath `artifacts/`; Supabase staging uses
the existing server-side credentials and explicit write gate. Browser requests
cannot supply a URL, file path, credential, cookie, or session.

The `/operator/events` page contains an acknowledgement-gated “Run public
Commerce MVP test” form. It states the public GET-only behavior, requires a
checkbox acknowledgement, and displays blocked/degraded/stale/succeeded
results. No spend, launch, store, payment, fulfillment, or messaging control
exists.

## Events and inspection

The run emits `public_signal_observed` events followed by the existing
`commerce_mvp_*` event family. Every event remains dry-run, advisory,
non-authoritative, manual-approval-required, and without launch/spend/publish/
store/payment/fulfillment authority. JSONL is the normal local target; inspect
an explicit artifact with:

```powershell
python scripts/query_canonical_events.py --jsonl artifacts/commerce-mvp-live-events.jsonl --timeline --json
python scripts/query_canonical_events.py --jsonl artifacts/commerce-mvp-live-events.jsonl --commerce-runs --json
```

No scheduler, retry loop, provider account, credentialed API, Shopify call, or
external mutation is involved. Cache files are local convenience snapshots and
can be removed without affecting business state.

## Deployment variables

Keep these server-side and default-off:

```text
MARKETOS_PUBLIC_COMMERCE_RUNS=0
MARKETOS_PUBLIC_SIGNAL_CACHE_DIR=artifacts/public-signal-cache
MARKETOS_EVENT_WRITE_JSONL_PATH=artifacts/commerce-mvp-live-events.jsonl
```

Before deploying, run `python scripts/deployment_smoke_check.py --local
--json` and `python scripts/local_mvp_smoke.py --include-shopify-fixture
--write-jsonl artifacts/local-mvp-smoke-events.jsonl --json`.

Before enabling API network mode, review query sensitivity, source attribution,
cache retention, artifact access, and the manual approval path. The next step
toward money-generating deployment is independently verified product and
landed-cost evidence, not automatic promotion from news coverage.

Public-run requests also carry a correlation ID and use the bounded MVP rate
limit described in [Phase 1 production hardening](PHASE1_PRODUCTION_HARDENING.md).
