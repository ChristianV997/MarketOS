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

## Safety and troubleshooting

- The page sends GET requests only and never creates, updates, publishes,
  launches, spends, pays, fulfills, or messages.
- JSONL reads are restricted by the backend to the configured file beneath
  `artifacts/`; the browser cannot supply a path.
- Empty JSONL results usually mean `MARKETOS_EVENT_READ_JSONL_PATH` is not set
  in the API process or the referenced artifact has not been generated.
- Supabase staging is optional. Its unconfigured state is surfaced as a
  readiness/error state and does not fall back to writing anything.

For Vercel/Railway deployments, keep the browser on the Vercel frontend and
configure the API's event-source environment variables only on the server
host. See `docs/CANONICAL_EVENT_READ_VIEWS.md` for the backend contract.
