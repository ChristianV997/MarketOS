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
provider payload. Every URL in a report is reduced to scheme, host, port, and
path; userinfo (`user:password@`), query values, and fragments are never kept,
including URLs echoed inside adapter warnings (redacted before the 180-character
cap, so truncation cannot leave a partial URL). Path segments that look like a
credential (the repository `sk-` marker rule; `sk_live_`/`sk_test_`, `ghp_`,
`github_pat_`, `xox*-`, `AKIA`, JWT, or `Bearer` shapes at a token boundary; also
when percent-encoded, repeatedly) are replaced with `[redacted]`. A URL whose host
carries one of those token shapes or a long `sk-` token, or whose port is
malformed, is dropped; a short `sk-` host label such as `www.sk-ii.com` is kept.
The path rule is deliberately conservative: a slug that starts a segment with
`sk-` (for example `/sk-ii-essence`) is also replaced.

`--output` must resolve (symlinks followed) to a path strictly under the
repository `artifacts/` directory, as a directory of artifacts, or as one JSON file when the path has a suffix.
Anything else, including `..` traversal, an absolute path elsewhere, `artifacts/`
itself, or a symlink leaving `artifacts/`, exits with status 2 before any report
is built or any file is written. The check is repeated for the directory and for
every file at write time (a live run can take minutes), and each file is opened
without following a symlink where the platform supports it; a swap detected at
those points exits with status 2 (files already written in that run may be
incomplete, and the message says so). This narrows the race to the instant between a
resolve and the following open; it does not eliminate it.

## Explicit public mode

```powershell
$env:MARKETOS_PHASE1_JS_RENDER="1"                  # optional fallback
$env:CRAWL4AI_ALLOWED_DOMAINS="example-store.com"  # required for JS
python scripts/run_phase1_public_market_benchmark.py --allow-network --max-candidates 3 --max-competitors-per-candidate 3 --markdown
```

This is a bounded public GET experiment only. `--allow-network` is the sole
switch that reaches the fetcher; the offline default and the API never do. It
delegates URL safety, robots handling, response limits, static extraction, and
optional JS extraction to the existing adapter. It never logs in, bypasses
CAPTCHA, places orders, mutates a provider, or uses CJ credentials. A candidate
URL containing userinfo (`https://user:password@host/...`) is rejected before the
fetcher is called (warning `competitor_url_with_userinfo_rejected`) because the
HTTP client would forward it as Basic authentication.

Public-mode output is market context only. It is not supplier proof, keeps the
`authenticated_supplier_evidence_not_live_observed` blocker, and has not been
live-validated by this change; the verification below is fixture/stub based.

## Using evidence

`GET /api/phase1/public-market-benchmark` only reads a server-configured
artifact under `artifacts/`; it never triggers a fetch and accepts no path, URL,
or network flag from the browser. Stored artifacts are re-sanitized on read, and
an artifact whose shape cannot be projected is returned as stored with the
warning `canonical_projection_unavailable` instead of failing. Without an
artifact it returns an explicitly labeled fixture fallback. `/operator/events` presents a
compact public-market card with coverage, observed offers, the top candidate,
and the remaining supplier blocker.

The offline runner also projects public offers into the canonical marketplace
pillar (`marketplace_trend_report`) and runs Product Opportunity Synthesis with
supplier/consumer pillars left missing. When `--output` is set it writes:

- `marketplace_trend_report.json`
- `opportunity_synthesis_report.json`

Public competitor prices are market context, not supplier costs. Demand
proxies and saturation from this projection are labeled as derived/assumed.
Strong public evidence with missing supplier proof produces the deterministic
next action: `set_cj_credentials_and_validate_candidate:<candidate_id>` on the
benchmark, and typically `validate_supplier_first` from synthesis.

## Verification status

- Fixture-tested: `tests/test_public_market_benchmark.py` (report, projection,
  URL sanitization, CLI output confinement, `--allow-network` gating with an
  injected fetcher).
- Integration-tested over mounted HTTP on the real backend app (routing, method
  handling, query handling, serialization, rate limit, artifact handling):
  `tests/integration/test_phase1_public_market_benchmark_api.py`.
- Not live-validated: no real public fetch is performed by the test suite.

## Threat model and known limits

The runner and API are local-operator tools: seeds and `--output` come from the
operator, and the API serves only a server-configured file. The defended
mistakes are credentials pasted into a candidate URL or path, an `--output`
pointing outside `artifacts/`, and `artifacts/` being redirected by a symlink
while a run is in progress.

- Not defended: a local actor who can already write inside `artifacts/` and wins
  a race inside a single write call, and, on platforms without `O_NOFOLLOW`
  (such as Windows), a symlinked leaf created after the directory re-check.
- Not defended: the API reads a configured artifact through the shared readiness
  loader, so a path swapped to a symlink between its containment check and the
  read is not re-validated. This needs the same local write access and only
  exposes JSON that is then redacted by that loader.
- Free-text redaction recognizes `http(s)://` URLs only; the adapter only echoes
  URLs it has validated as `http(s)`.
- A credential-shaped path segment in a live-mode candidate URL is still sent to
  the target site (the operator asked for that page); only the report is redacted.
