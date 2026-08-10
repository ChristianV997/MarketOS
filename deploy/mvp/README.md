# MVP Island operator runbook

This directory is a deployment profile, not a second runtime. It permits a
small useful MarketOS deployment while leaving broader experimental modules in
the repository but outside the recommended process topology.

## Fastest staging path

1. Create a Supabase project only if durable hosted events are needed. Apply
   `deploy/supabase/schema.sql`; do not expose the service-role key.
2. Deploy `frontend/` to Vercel and set only `VITE_API_BASE_URL`.
3. Deploy FastAPI to Railway or Render using the startup command in
   `marketos.mvp.json`. Set `MARKETOS_MVP_MODE=1`, an explicit
   `ALLOWED_ORIGINS`, and no live-commerce variables.
4. Probe `/health`, then `/ready`. Do not add a worker, cron, or queue yet.
5. Use `python scripts/ingest_public_signals.py --fixtures --json` to verify
   the deterministic evidence path. A real public read remains an intentional
   manual command with `--allow-network`.
6. Run `python scripts/mvp_readiness.py --json` in the deployment environment.
7. Run `python scripts/deployment_smoke_check.py --backend-url <api-url> --json`
   and verify the operator dashboard at `/operator/events`.

## What goes where

| Environment | Safe values |
| --- | --- |
| Vercel frontend | `VITE_API_BASE_URL`; optional public PostHog key only |
| FastAPI service | MVP mode, CORS, optional Sentry/PostHog/Supabase server values |
| Supabase | Schema; server-only canonical event access; no anon policies yet |
| Cloudflare | DNS/TLS/WAF in front of selected hosts |

Never put `SUPABASE_SERVICE_ROLE_KEY`, Resend, provider, model-router, or
Cloudflare API keys in `VITE_*` variables or browser-visible configuration.

## MVP acceptance check

The island is ready for a staging deployment when the readiness report has no
unsafe live flags, the API responds to its two probes, the frontend builds, and
the fixture public-signal flow produces only advisory canonical events. A
missing Supabase configuration is not a failure: JSONL remains the default
local repository until an explicit wiring decision is tested.

Use `docs/MVP_DEPLOYMENT_SMOKE_CHECKS.md` for the complete local, Railway,
Render, and Vercel verification sequence. The machine-readable environment
contract is `deploy/mvp/env.contract.json`.

## Out of scope

This profile does not schedule ingestion, activate QStash, provision a queue,
enable Supabase Auth policies, add dashboard authentication, send emails,
configure AI gateways, or start any commercial mutation. Each needs its own
small promotion plan with cost review, operational ownership, tests, and a
rollback path.
