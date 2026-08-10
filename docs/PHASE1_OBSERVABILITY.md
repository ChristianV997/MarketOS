# Phase 1 observability

MarketOS uses one optional observability stack for the current MVP:

- Sentry for backend exceptions and conservative traces.
- PostHog for explicit frontend product events.
- Existing request-correlation and redacted Python logs for diagnostics.

Telemetry is optional and fail-open. If a DSN, browser project key, SDK, or
telemetry service is unavailable, the API, dashboard, public-run gates, and
JSONL event workflows continue to work.

## Sentry backend

Configure these only on Railway/Render, never in Vercel or `VITE_*` variables:

```text
SENTRY_DSN=
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=
SENTRY_TRACES_SAMPLE_RATE=0.0
```

Initialization occurs during FastAPI startup and is idempotent. `send_default_pii`
is disabled. Request IDs, safe route families, method, MVP mode, and read-only
state may be attached as tags. Request bodies, cookies, authorization headers,
Shopify/customer data, provider credentials, and full environment mappings are
never attached.

Expected blocked, rate-limited, stale-cache, and degraded states are ordinary
operator outcomes and are not emitted as Sentry exceptions. Unexpected handler,
parser, repository, or query failures may be captured by the Sentry FastAPI
integration when configured.

## PostHog frontend

Configure only the browser-safe project key on Vercel:

```text
VITE_POSTHOG_KEY=
VITE_POSTHOG_HOST=https://us.i.posthog.com
```

The existing client has autocapture and automatic pageview capture disabled.
`frontend/src/lib/analytics.ts` permits only explicit allowlisted events and
properties. It sends query length, not query text; it never sends workspace
names, customer data, Shopify payloads, credentials, or form bodies.

Tracked events include dashboard views/refresh/filter/source interactions and
public-run started/succeeded/blocked/degraded/stale-cache outcomes. There is no
session recording in this phase.

## Correlation and privacy

Use the API response `X-Request-ID` to correlate an operator action with safe
application logs and, when configured, Sentry. Telemetry sanitization reuses the
existing safe logging redaction patterns and additionally removes email, phone,
address, customer identity, request data, headers, cookies, and query strings.

## Readiness and verification

```powershell
python scripts/telemetry_readiness.py --json
python scripts/telemetry_readiness.py --markdown
python scripts/telemetry_readiness.py --env-file deploy/mvp/.env.mvp.example --json
python scripts/telemetry_readiness.py --test-sanitization --json
python scripts/deployment_smoke_check.py --env-file deploy/mvp/.env.mvp.example --json
```

These commands make no telemetry network calls and never print DSNs or keys.
The local sanitization test is deterministic. A real Sentry/PostHog project
smoke is intentionally operator-managed and is not required for tests.

## Not included

This phase does not add another observability vendor, distributed tracing,
business KPI dashboards, WAF metrics, automatic alerts, or background jobs.
Future work may add a real project smoke using operator-supplied configuration,
Cloudflare/WAF metrics, and longer-term business reporting.
