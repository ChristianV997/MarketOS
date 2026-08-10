# Canonical Event Read Views

## Purpose

MarketOS operators can inspect advisory canonical events, timelines, Commerce
MVP runs, and Shopify read-only imports without adding a dashboard or a write
path. The query service is read-only and summarizes payload/metadata keys by
default instead of returning raw payload values.

## Sources

- **JSONL:** local CLI mode; no credentials. Supply an explicit `--jsonl` path.
- **Supabase staging:** server-side only; supply `--supabase-staging`. It needs
  `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`, but not the staging write
  gate. It never writes.

The FastAPI routes use JSONL only when the operator configures
`MARKETOS_EVENT_READ_JSONL_PATH` to a file beneath `artifacts/`. This avoids an
arbitrary local-file read parameter. Supabase keys are never accepted from a
request or returned in a response.

## CLI

```powershell
python scripts/query_canonical_events.py --jsonl artifacts/commerce-mvp-shopify-events.jsonl --timeline --markdown
python scripts/query_canonical_events.py --jsonl artifacts/commerce-mvp-shopify-events.jsonl --commerce-runs --json
python scripts/query_canonical_events.py --jsonl artifacts/shopify-readonly-events.jsonl --shopify-imports --markdown
python scripts/query_canonical_events.py --supabase-staging --workspace-id demo --limit 50 --json
```

Filters include workspace, event type, aggregate type/ID, correlation ID,
source, offset, limit, and ascending/descending deterministic ordering.

## API

GET-only routes are mounted at `/api/events`, `/api/events/timeline`,
`/api/events/commerce-runs`, `/api/events/shopify-imports`, and
`/api/events/readiness`. They contain no POST/PUT/PATCH/DELETE endpoint.

## Safety and privacy

The views preserve canonical replay hashes and authority flags while exposing
payload/metadata summaries only. Shopify events were redacted before writing
and no raw Shopify PII is returned by these views. The service never creates,
updates, publishes, launches, spends, sends, fulfills, or pays.

## Deployment next step

Deploy the FastAPI process server-side, configure one allowed JSONL artifact
path or a server-only Supabase staging connection, then add a minimal frontend
viewer only after its workspace authorization model is reviewed.
