# Operator Event Dashboard

The frontend route `/operator/events` is a read-only operator surface for
canonical event timelines, Commerce MVP runs, Shopify import summaries, and
event-source readiness. It uses the existing GET-only `/api/events` routes;
it has no action controls, credential inputs, browser Supabase client, or
local-file-path field.

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
