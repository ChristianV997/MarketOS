# Phase 1 Live Validation Runbook

The Phase 1 intelligence stack (Supplier Evidence, Competition Intelligence,
Opportunity Scoring, Product Research) is fully fixture-tested and CI-tested,
but has never had a real fetch succeed against a live public page: every
sandbox used to build it blocks outbound HTTPS to general web domains at the
proxy `CONNECT` layer (confirmed repeatedly — DNS resolves fine, every fetch
attempt fails with `ProxyError`/`Tunnel connection failed: 403 Forbidden`,
identical across `cjdropshipping.com`, `amazon.com`, `etsy.com`,
`aliexpress.com`, and arbitrary manufacturer/Shopify storefront domains).
This runbook is for running the one remaining leg — a real fetch — from an
environment that isn't behind that proxy.

## What you're proving

```text
real public page -> structured extraction -> normalized supplier evidence
-> normalized competition evidence -> market pricing summary
-> margin intelligence -> opportunity scoring -> product research portfolio
-> Commerce MVP economics -> canonical events -> API/dashboard read views
```

Every other link in this chain is already proven by the existing test suite
(`pytest -q` — 3310+ passed). `scripts/run_phase1_live_validation.py` is a
thin harness over the same entrypoints those tests exercise
(`gather_supplier_evidence`, `gather_market_intelligence`,
`run_commerce_mvp_slice`, `build_research_portfolio`, `event_query_report`)
— it adds no new extraction or scoring logic, just orchestration and a
combined report.

## Run locally (Windows PowerShell)

```powershell
cd C:\Users\HP\Documents\MarketOS
git switch main
git pull origin main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python scripts\run_phase1_live_validation.py `
  --supplier-url "https://www.cjdropshipping.com/product/<a-real-product-slug>.html" `
  --competitor-urls "https://www.etsy.com/listing/<id>,https://<a-shopify-store>.myshopify.com/products/<slug>,https://<manufacturer-site>/products/<slug>" `
  --query "portable espresso maker" `
  --allow-network `
  --markdown
```

Substitute real URLs you have — the harness never guesses or fabricates a
product page; it only observes whatever you point it at. `--supplier-url`
should be one CJ Dropshipping product page (public, no login).
`--competitor-urls` is comma-separated (3-5 recommended); prioritize pages
likely to expose `schema.org Product` JSON-LD — Shopify and WooCommerce
product pages are the most reliable, followed by manufacturer sites; Etsy/
Amazon/AliExpress often work but may block harder (report the failure mode
honestly if so — see "Reading the report" below).

Without `--allow-network`, the harness runs the exact same chain in
dry-run/simulated mode (no network calls at all) — useful to confirm the
harness itself works before attempting a real fetch.

Output: `artifacts\phase1_live_validation\<timestamp>\validation_report.json`
(and `.md` with `--markdown`), plus `events.jsonl` in the same directory —
the actual canonical events this run produced, replayable through the
existing `scripts\query_canonical_events.py` or the operator dashboard.

To measure the run without reading raw artifacts manually, use the deterministic
evaluation framework:

```powershell
python scripts/evaluate_commerce_run.py `
  --workspace artifacts/phase1_live_validation/<timestamp> `
  --json
```

See [COMMERCE_EVALUATION_FRAMEWORK.md](COMMERCE_EVALUATION_FRAMEWORK.md) for
metric definitions, Run A/Run B comparison, and read-only evaluation API views.

### Authenticated CJ supplier comparison

Public CJ product pages were proven insufficient in the Phase 1 benchmark, so
the optional authenticated read-only adapter is evaluated with a separate
offline-first, one-probe workflow. It is disabled unless server-side CJ
credentials, `MARKETOS_SUPPLIER_AUTH_READONLY=1`, and `--allow-network` are
all present. Use
[PHASE1_CJ_LIVE_VALIDATION_PACK.md](PHASE1_CJ_LIVE_VALIDATION_PACK.md) for the
exact command and sanitized artifact contract; it can compare a CJ result with
the existing static/JS validation artifact without adding a second evaluator.

## Run on Railway (deployed backend)

Required environment variables — all already used by the existing gated
public-network paths this harness composes through, none newly invented:

| Variable | Purpose |
|---|---|
| `MARKETOS_PUBLIC_COMMERCE_RUNS=1` | Server-side gate for `POST /api/commerce-mvp/public-run` (required if validating through the API rather than the CLI). |
| `MARKETOS_SUPPLIER_EVIDENCE_LIVE=1` | Server-side gate for `attempt_supplier_evidence` on that same route. |
| `MARKETOS_COMPETITION_EVIDENCE_LIVE=1` | Server-side gate for `attempt_competition_evidence` on that same route. |
| `MARKETOS_EVENT_READ_JSONL_PATH` | Points the read API (`/api/events/*`) at the JSONL file to read back — set this to wherever you write validation events. |
| `MARKETOS_EVENT_WRITE_JSONL_PATH` | Optional; only relevant if writing through the API's `event_target: jsonl` path rather than the CLI's `--out-dir`. |

The CLI harness itself (`scripts/run_phase1_live_validation.py`) does not
read any of these — it calls the Python entrypoints directly, so it needs
none of the API-layer gates. Use the CLI for a one-shot Railway shell/SSH
validation run; use the API + these env vars only if you specifically want
to validate the deployed HTTP surface (`POST /api/commerce-mvp/public-run`
with `attempt_supplier_evidence: true, attempt_competition_evidence: true,
use_opportunity_ranking: true, supplier_candidate_urls: [...],
competitor_urls: [...]`) rather than the harness script.

```bash
railway run python scripts/run_phase1_live_validation.py \
  --supplier-url "https://www.cjdropshipping.com/product/<slug>.html" \
  --competitor-urls "https://<real-url-1>,https://<real-url-2>,https://<real-url-3>" \
  --allow-network --markdown
```

## Reading the report

`validation_report.json`'s top-level `status` is one of:

- **`pass`** — real supplier or competition evidence was observed.
- **`degraded`** — pages were reachable but exposed no usable structured
  product data (no `schema.org Product` JSON-LD) — the pages themselves
  may be JS-rendered, or genuinely lack structured data. This is the result
  that justifies the optional Crawl4AI fallback below; it is not a pass.
- **`blocked`** — network egress itself was denied (the sandbox result
  documented throughout this repo's Phase 1 docs).
- **`degraded_dry_run`** — `--allow-network` wasn't passed; nothing was
  attempted.

`network_status.diagnosis` gives one entry per target hostname with an
exact `failure_mode` — `dns_failure`, `proxy_block`, `timeout`,
`tls_error`, `connection_error`, `redirect_rejected`, or `reachable` — plus
the raw exception detail, independent of (and more granular than) the
adapters' own conservative `"robots.txt could not be verified"` bucket
(which fires whenever robots.txt is unreachable for *any* reason — this
diagnosis tells you which reason).

Every extracted field carries its own provenance
(`observed`/`derived`/`assumed`/`missing`/`malformed`/`stale`/`conflicting`)
in `supplier_evidence.field_status_summary` and each competitor offer's
`field_status` under `competition_evidence.offers[].field_status` — nothing
is ever filled in with a guess.

`api_dashboard_read_path` confirms the four decoded read-API summaries
(`commerce_runs`, `opportunity_rankings`, `competition_summaries`,
`research_portfolios`) are populated from the real events this run wrote —
proving the dashboard tabs would show real data for this run, without
needing to actually start the FastAPI server.

## Optional JS-rendered extraction after a degraded result

Only use this after a real validation run reports `degraded`. Install the
reviewed optional profile in the operator environment, then explicitly set
the render gate and the exact target-domain allowlist:

```powershell
python scripts\check_phase1_crawl4ai_runtime.py --json

# If the preflight reports Python 3.14 without a compatible optional profile,
# create an isolated CPython 3.12 or 3.13 environment before installing.
pip install -r requirements-oss.txt
$env:MARKETOS_PHASE1_JS_RENDER = "1"
$env:CRAWL4AI_ALLOWED_DOMAINS = "www.cjdropshipping.com,wacaco.com,aeropress.com"
# Windows PowerShell only: Crawl4AI/Rich console output needs UTF-8.
$env:PYTHONIOENCODING = "utf-8"
# Optional local-runtime override only: use an installed Chrome channel when
# Playwright's chromium-headless-shell payload is unavailable.
$env:MARKETOS_CRAWL4AI_BROWSER_CHANNEL = "chrome"
python scripts\run_phase1_live_validation.py `
  --supplier-url "https://www.cjdropshipping.com/product/<real-slug>.html" `
  --competitor-urls "https://www.wacaco.com/products/<real-slug>,https://aeropress.com/products/<real-slug>" `
  --query "portable espresso maker" --allow-network --markdown
```

The fallback remains robots-aware and emits only structured Product records.
It does not bypass CAPTCHA, login, anti-bot controls, or redirects. If the
optional dependency is missing or the domain is not allowlisted, the run
degrades rather than silently widening access. A `pass` still requires an
observed supplier or competition field in `validation_report.json`.

The optional profile is intentionally not a default API dependency. In the
paired benchmark on CPython 3.14, the reviewed `crawl4ai==0.8.6` profile
could not install because its `lxml~=5.3` dependency fell back to a source
build without compatible libxml2 headers. The preflight above reports that
runtime blocker before attempting installation; use a CPython 3.12 or 3.13
operator environment rather than changing default dependencies or bypassing
the browser/runtime boundary.

For the sanitized CPython 3.12 paired benchmark and its CJ public-page
diagnosis, see [Phase 1 live validation results](PHASE1_LIVE_VALIDATION_RESULTS.md).

## Optional authenticated supplier evidence

The public CJ page limitation is now complemented by an explicit, server-side
authenticated read-only CJ catalog path. It is **not enabled by default** and
does not use the public-page URL. See
[Phase 1 Authenticated Read-Only Supplier Evidence](PHASE1_AUTH_READONLY_SUPPLIER.md)
for the provider decision, environment contract, endpoint allowlist, and
credentialed operator command. Missing credentials must remain a structured
`credential_missing` result; do not substitute login scraping or private-page
access.

`MARKETOS_CRAWL4AI_BROWSER_CHANNEL` is deliberately unset by default. Set it
only after a local Playwright launch probe confirms the requested channel is
installed; it does not alter the allowlist, robots policy, or default runtime.
On Windows PowerShell, set `PYTHONIOENCODING=utf-8` for the optional worker so
third-party Rich console output cannot terminate the render before navigation.

## If a fetch still fails from an unrestricted environment

That's real, useful information — capture it exactly as reported, don't
retry with a different technique to force a result:

- **`missing JSON-LD`/`no_structured_product_data_found`**: the page is
  reachable but has no `schema.org Product` data. First run the explicit
  optional fallback above. If it still fails, document the specific page;
  never bypass access controls or turn arbitrary page prose into evidence.
- **`robots.txt disallow`** (a real disallow rule, not an unreachable
  robots.txt): the adapter is working correctly — it will not fetch a page
  robots.txt disallows. This is a policy boundary, not a bug.
- **anti-bot/CAPTCHA**: do not attempt to bypass it. Report the page and
  move to a different competitor source for that product.

## Do not

- Use credentials of any kind.
- Bypass a CAPTCHA.
- Scrape authenticated/private data.
- Create, update, or mutate anything on CJ, the competitor sites, or any
  provider — this harness (and everything it calls) is read-only by
  construction; there is no code path in it that places an order, creates
  a listing, or spends anything.
