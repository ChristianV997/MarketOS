# Phase 1 Public Market Evidence Benchmark

This bounded, read-only runner adds repeatable multi-candidate public-market
context to the Evidence Benchmark Matrix. It reuses the existing
robots-aware competitor adapter and matrix; it is not supplier proof, a new
provider, or commerce execution.

## Offline default

```powershell
python scripts/run_phase1_public_market_benchmark.py --json
python scripts/run_phase1_public_market_benchmark.py --markdown
python scripts/run_phase1_public_market_benchmark.py --output artifacts/phase1_public_market/latest --markdown
```

Default mode uses sanitized fixture/demo offers, makes no network calls, and
needs no credentials. Written artifacts contain only normalized public evidence
and summaries: no raw HTML, browser trace, cookie, auth header, secret, or raw
provider payload.

## Explicit public mode

```powershell
$env:MARKETOS_PHASE1_JS_RENDER="1"                  # optional fallback
$env:CRAWL4AI_ALLOWED_DOMAINS="example-store.com"  # required for JS
python scripts/run_phase1_public_market_benchmark.py --allow-network --max-candidates 3 --max-competitors-per-candidate 3 --markdown
```

This is a bounded public GET experiment only. It delegates URL safety, robots
handling, response limits, static extraction, and optional JS extraction to
the existing adapter. It never logs in, bypasses CAPTCHA, places orders,
mutates a provider, or uses CJ credentials.

## Using evidence

`GET /api/phase1/public-market-benchmark` only reads a server-configured
artifact under `artifacts/`; it never triggers a fetch. Without an artifact it
returns an explicitly labeled fixture fallback. `/operator/events` presents a
compact public-market card with coverage, observed offers, the top candidate,
and the remaining supplier blocker.

Public competitor prices are market context, not supplier costs. Strong public
evidence with missing supplier proof produces the deterministic next action:
`set_cj_credentials_and_validate_candidate:<candidate_id>`.
