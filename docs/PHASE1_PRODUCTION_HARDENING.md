# Phase 1 production hardening

This document describes the deliberately small hardening layer for the current
MarketOS MVP deployment path: Railway or Render for FastAPI, Vercel for the
frontend, Google News RSS as the only public network source, JSONL by default,
and optional server-side Supabase staging.

## What is covered

- Explicit CORS origin parsing and validation.
- Request correlation through `X-Request-ID`.
- Safe response markers: `X-MarketOS-MVP-Mode` and, for event/public-run
  routes, `X-MarketOS-Read-Only`.
- Summary-only request logging with secret and body redaction.
- In-memory per-client rate limits for public Commerce runs and event reads.
- Readiness and deployment smoke reports that expose booleans and counts, not
  credentials.

## CORS

Set `ALLOWED_ORIGINS` to a comma-separated list of exact frontend origins, for
example `https://marketos.example` or `http://localhost:5173`. Wildcard `*` is
warned in development and blocked when MVP mode or the public-run gate is on.
Browser credentials are disabled by the MVP middleware.

## Request IDs and logging

The API accepts a short safe `X-Request-ID` or generates one. The same value is
returned on the response and is available in summary logs. Request bodies,
authorization headers, cookies, API keys, service-role keys, and provider token
values are not logged. Logs contain method, path, status, duration, route
family, and safe gate/read-only indicators only.

## Rate limits

The public-run route defaults to 10 requests per 600 seconds per client IP.
Canonical event reads default to 300 requests per 600 seconds per client IP.
Override locally or per single-process deployment with:

```text
MARKETOS_PUBLIC_RUN_RATE_LIMIT=10
MARKETOS_PUBLIC_RUN_RATE_WINDOW_SECONDS=600
MARKETOS_EVENT_READ_RATE_LIMIT=300
MARKETOS_EVENT_READ_RATE_WINDOW_SECONDS=600
```

Exceeded limits return HTTP 429 with `Retry-After`, `status=rate_limited`, and
`mutated=false`. Reset helpers exist for tests. This is single-process MVP
protection only; it is not a distributed limiter.

## Verification

```powershell
python scripts/deployment_smoke_check.py --env-file deploy/mvp/.env.mvp.example --json
python -m pytest tests/contracts/test_cors_validation.py tests/contracts/test_safe_logging.py tests/contracts/test_rate_limit.py -q
python -m pytest tests/integration/test_request_context_middleware.py tests/integration/test_public_run_rate_limit.py tests/integration/test_event_read_rate_limit.py -q
```

With the API running, the smoke checker probes `/health`, `/ready`, event
readiness/timeline, the default-off public-run response, and request-ID
headers. No provider call is made by the checker.

## Deployment notes

On Railway or Render, configure exact `ALLOWED_ORIGINS`, keep
`MARKETOS_PUBLIC_COMMERCE_RUNS=0` until manually reviewed, and keep
`MARKETOS_SUPABASE_CANONICAL_EVENTS=0`. Vercel receives only public `VITE_*`
configuration such as `VITE_API_BASE_URL`; it never receives server secrets.

## Not solved here

This does not provide distributed rate limiting, WAF/bot protection,
authentication or tenancy, payment/commerce security, or long-term telemetry.
Future hardening can evaluate Cloudflare WAF, Redis/Upstash distributed limits,
Supabase Auth/RLS, Sentry/PostHog production configuration, and authenticated
operator actions.
