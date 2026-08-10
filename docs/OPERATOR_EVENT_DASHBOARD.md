# Operator Event Dashboard

The frontend route `/operator/events` is a read-only operator surface for
canonical event timelines, Commerce MVP runs, Shopify import summaries,
opportunity-ranking scores, competition/pricing intelligence, research
portfolios, and event-source readiness. It uses the existing GET-only
`/api/events` routes; it has no action controls, credential inputs,
browser Supabase client, or local-file-path field.

The **Opportunity ranking** tab shows every scored candidate for a run: its
composite score, confidence, observed/derived/assumed/unknown percentage
split, top reasons, risks, unknowns, recommended action, and an expandable
per-dimension breakdown table (raw value, normalized value, weight,
contribution, provenance, reason). It reads
`/api/events/opportunity-rankings`, which decodes real
`opportunity_scoring_events()` payloads instead of the generic timeline's
key-list-only summary — see
[Opportunity Scoring](OPPORTUNITY_SCORING.md#dashboard-view). The **Run
public Commerce MVP test** form has a **Rank candidates with opportunity
scoring** checkbox that passes `use_opportunity_ranking=true` through to
`/api/commerce-mvp/public-run`.

The **Competition & pricing** tab shows, per run: observed competitor
count, median/min/max price, market saturation and maturity, confidence,
a supplier-vs-market margin card (observed gross margin, margin range,
supplier advantage), and an expandable observed-price-distribution table
(title, source, price, brand, seller, rating, reviews, per-offer
confidence) — the evidence drill-down behind the Competition Intelligence
scoring dimensions. It reads `/api/events/competition-summaries` — see
[Competition Intelligence](COMPETITION_INTELLIGENCE.md#read-api-and-dashboard-view).
The run form has a **Gather public competitor pricing** checkbox (with a
competitor-URL input) that passes `attempt_competition_evidence`/
`competitor_urls` through — it only takes effect together with the
opportunity-ranking checkbox and requires the server-side
`MARKETOS_COMPETITION_EVIDENCE_LIVE` gate.

The **Research portfolio** tab shows, per run: bucket counts (top/
emerging/undervalued/high-risk/high-uncertainty/rejected), research
quality metrics (evidence/supplier/competition/pricing coverage,
completeness, unknown ratio, freshness, market confidence), top movers
(from the most recent ranking comparison), and an expandable cluster list
(name, member count, confidence, price range, supplier/competition
diversity). It reads `/api/events/research-portfolio` — see
[Product Research](PRODUCT_RESEARCH.md#read-api-and-dashboard-view). This
tab has no run-form control of its own — a portfolio is built via
`scripts/run_product_research_engine.py` (or programmatically) and its
events written to the configured JSONL/Supabase source, same as any other
canonical-event read view.

## Run locally

First create advisory JSONL events, then configure the FastAPI process with an
allowed artifact path:

```powershell
python scripts/run_commerce_mvp_slice.py --fixture tests/fixtures/commerce_mvp/public_signals.json --shopify-fixture tests/fixtures/shopify_readonly/shopify_sample.json --query "portable espresso maker" --write-jsonl artifacts/commerce-mvp-shopify-events.jsonl --json
$env:MARKETOS_EVENT_READ_JSONL_PATH = "artifacts/commerce-mvp-shopify-events.jsonl"
```

Run the API server and Vite frontend, then open `/operator/events`. The source
selector supports JSONL and optional Supabase staging. Supabase reads happen
only in the server process and require server-side `SUPABASE_URL` and
`SUPABASE_SERVICE_ROLE_KEY`; neither value is sent to the browser.

The page also includes an acknowledgement-gated **Run public Commerce MVP
test** form. It accepts only a query, workspace label, bounded signal count,
and explicit event target. The backend must have
`MARKETOS_PUBLIC_COMMERCE_RUNS=1`; the form cannot provide credentials, URLs,
cookies, or file paths. The source is fixed to Google News RSS.

## Safety and troubleshooting

- The page sends GET requests only and never creates, updates, publishes,
  launches, spends, pays, fulfills, or messages.
- JSONL reads are restricted by the backend to the configured file beneath
  `artifacts/`; the browser cannot supply a path.
- Empty JSONL results usually mean `MARKETOS_EVENT_READ_JSONL_PATH` is not set
  in the API process or the referenced artifact has not been generated.
- Supabase staging is optional. Its unconfigured state is surfaced as a
  readiness/error state and does not fall back to writing anything.
- Public runs are manually invoked and report `blocked`, `degraded`,
  `stale_cache`, or `succeeded`; they never authorize a launch or spend.

For Vercel/Railway deployments, keep the browser on the Vercel frontend and
configure the API's event-source environment variables only on the server
host. Run `python scripts/deployment_smoke_check.py --backend-url <api-url>
--json` before opening the dashboard. See
`docs/MVP_DEPLOYMENT_SMOKE_CHECKS.md` and
`docs/CANONICAL_EVENT_READ_VIEWS.md` for the deployment/backend contracts.

The event-read API returns correlation headers and applies the Phase 1
single-process read limit; see [production hardening](PHASE1_PRODUCTION_HARDENING.md).

Dashboard interactions use explicit, sanitized PostHog events only when
`VITE_POSTHOG_KEY` is configured; see [Phase 1 observability](PHASE1_OBSERVABILITY.md).
