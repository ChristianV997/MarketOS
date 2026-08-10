# Phase 1 MVP Deployment Smoke Checks

This runbook verifies the current deployable MarketOS slice without deploying
anything or calling provider APIs. The selected path is Vercel for the Vite
frontend and Railway for the FastAPI backend. Render is an equivalent fallback.
JSONL remains the default event repository; Supabase staging is optional.

## Local contract check

```powershell
python scripts/deployment_smoke_check.py --local --json
python scripts/deployment_smoke_check.py --env-file deploy/mvp/.env.mvp.example --markdown
```

The check parses `deploy/mvp/env.contract.json`, classifies missing values,
checks default-off gates, rejects event/cache paths outside `artifacts/`,
checks frontend env files for forbidden secret names, and prints only redacted
configuration state. It performs no network request unless a URL is supplied.

## Local end-to-end smoke

```powershell
python scripts/local_mvp_smoke.py --include-shopify-fixture --write-jsonl artifacts/local-mvp-smoke-events.jsonl --json
python scripts/query_canonical_events.py --jsonl artifacts/local-mvp-smoke-events.jsonl --timeline --json
python scripts/query_canonical_events.py --jsonl artifacts/local-mvp-smoke-events.jsonl --commerce-runs --json
```

By default this uses the deterministic Commerce MVP fixture and no network.
Add `--allow-public-network` only for one operator-authorized Google News RSS
read. Add `--skip-frontend-build` when the Vite build has already been checked.

## Railway backend

1. Create a Railway service from the repository.
2. Use `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`.
3. Set `MARKETOS_MVP_MODE=1`, explicit `ALLOWED_ORIGINS`, and the three
   server-side artifact paths from the env contract.
4. Keep `MARKETOS_PUBLIC_COMMERCE_RUNS=0` initially.
5. Keep `MARKETOS_SUPABASE_CANONICAL_EVENTS=0` initially.
6. Probe the service:

```powershell
python scripts/deployment_smoke_check.py --backend-url https://<railway-api> --json
```

The endpoint smoke verifies `/health`, `/ready`, canonical-event readiness,
timeline access, and that a public-run request is blocked while the gate is
off. It never prints server values or submits a provider request.

## Render fallback

Create a Render Web Service from the same repository, use
`requirements.txt`, the same Uvicorn command, and the same env contract. Do
not run Railway and Render as active backends for the initial MVP; choose one.

## Vercel frontend

1. Import the `frontend/` directory as the Vercel project.
2. Build with `npm install && npm run build`.
3. Set only `VITE_API_BASE_URL=https://<railway-or-render-api>`.
4. Optionally set the public `VITE_POSTHOG_KEY`; never set server secrets in
   Vercel browser variables.
5. Open `/operator/events` and verify readiness, filters, timeline, and the
   acknowledgement-gated public-run form.

```powershell
cd frontend
npm run build
```

## Environment contract

Required backend deployment values are `ALLOWED_ORIGINS`,
`MARKETOS_MVP_MODE=1`, `MARKETOS_EVENT_READ_JSONL_PATH`,
`MARKETOS_EVENT_WRITE_JSONL_PATH`, and `MARKETOS_PUBLIC_SIGNAL_CACHE_DIR`.
All event/cache paths must remain beneath `artifacts/`.

Public API runs require the separate server gate
`MARKETOS_PUBLIC_COMMERCE_RUNS=1`. JSONL writes still require an explicit event
target. Supabase additionally requires `SUPABASE_URL`,
`SUPABASE_SERVICE_ROLE_KEY`, and `MARKETOS_SUPABASE_CANONICAL_EVENTS=1`.

Never put Supabase service-role, Stripe, Shopify, Meta, TikTok, supplier,
payment, refund, or fulfillment credentials in frontend files or `VITE_*`
variables.

## Troubleshooting

- CORS errors: set `ALLOWED_ORIGINS` to the exact Vercel origin.
- Empty events: set the API process's `MARKETOS_EVENT_READ_JSONL_PATH` to an
  existing artifact or explicitly generate one with `--write-jsonl`.
- Public run blocked: keep the block unless the operator has reviewed the
  public/no-auth use case, then set the server gate and use the dashboard
  acknowledgement.
- Supabase unconfigured: expected for JSONL-first MVP; use staging only after
  server-only key and schema review.
- Vite large chunk warning: build remains valid; code splitting is a later
  optimization and not a deployment blocker.

This smoke layer does not enable payments, Shopify mutation, supplier orders,
inventory changes, fulfillment, refunds, customer messaging, ad spend,
publishing, schedulers, or autonomous execution.

See [Phase 1 production hardening](PHASE1_PRODUCTION_HARDENING.md) for exact
CORS validation, request IDs, redacted logs, and in-memory rate-limit checks.

Optional Sentry/PostHog readiness is documented in
[Phase 1 observability](PHASE1_OBSERVABILITY.md); missing telemetry never blocks
the MVP smoke.
