# SaaS integration scorecard

This is a deployment decision aid, not a procurement approval. Cost categories
are qualitative because pricing changes; verify current pricing, regions,
limits, and terms before committing spend.

| Service | MVP usefulness | Complexity | Lock-in | Repo fit / replaces | Decision |
| --- | --- | --- | --- | --- | --- |
| Supabase | High | Medium | Medium | Replaces ad-hoc durable MVP data; Auth/Storage later | **Use now for schema + server events** |
| Vercel | High | Low | Medium | Replaces frontend hosting/CDN work | **Use now** |
| Railway | High | Low | Medium | Simple FastAPI deployment | **Use now / preferred API path** |
| Render | High | Low | Medium | Railway alternative with simple web services | **Evaluate as equivalent** |
| Fly.io | Medium | Medium | Low-medium | More deployment control | **Defer unless regional/runtime need** |
| Cloudflare DNS/CDN/WAF | Medium | Low | Medium | DNS, TLS, edge protection | **Use now for DNS; evaluate extras** |
| Cloudflare Workers/R2/D1/Queues | Medium | Medium | Medium | Could replace edge/storage/queue components | **Defer for first API MVP** |
| Upstash Redis/QStash | Medium | Low-medium | Medium | Replaces self-hosted Redis/scheduler for HTTP jobs | **Evaluate after manual workflow proves value** |
| PostHog | Medium | Low | Medium | Existing default-off frontend/server telemetry | **Use now if analytics is needed** |
| Sentry | High | Low | Medium | Existing default-off error reporting | **Use now in staging/production** |
| Resend | Low now | Low | Medium | Transactional report email | **Defer until human-approved email exists** |
| Trigger.dev | Medium | Medium | Medium | Durable workflow option | **Evaluate after a genuine async job** |
| Inngest | Medium | Medium | Medium | Event-driven durable functions | **Evaluate alongside Trigger.dev** |
| OpenRouter | Low now | Low | Medium | Model routing/cost visibility | **Evaluate only; no automatic routing** |
| Vercel AI Gateway | Low now | Low | Medium | Gateway if Vercel is selected | **Evaluate only** |
| Cloudflare AI Gateway | Low now | Low-medium | Medium | Gateway/observability at edge | **Evaluate only** |
| 9Router | Low now | Unknown | Higher | Alternate model routing | **Defer pending security/provenance review** |
| Ruflo | Low | Unknown | Unknown | Not required by MVP | **Defer** |
| Qdrant Cloud / managed vector | Low now | Medium | Medium | Replaces optional local vector runtime | **Defer; MVP uses no heavy vector path** |
| Neon | Medium | Low | Medium | Supabase Postgres alternative | **Evaluate only if Auth/Storage not needed** |
| Clerk/Auth0 | Medium later | Medium | High | Auth alternatives | **Defer; Supabase Auth is the first comparison** |

## Recommended sequence

1. Deploy the Vite frontend to Vercel and the existing FastAPI app to Railway.
2. Create an operator-owned Supabase project; apply the MVP schema but leave
   the canonical adapter opt-in until staging tests prove its behavior.
3. Enable Sentry and PostHog only with environment variables and a documented
   privacy review.
4. Use Cloudflare for DNS/TLS/WAF as operational needs justify it.
5. Add Upstash QStash only after manual public-signal runs demonstrate that a
   scheduled job is valuable and a human review path is defined.

## Why not build these internally

MVP differentiation is MarketOS evidence normalization, canonical events,
dry-run economics, and advisory outputs—not an identity system, database HA,
CDN, task queue, error tracker, or email delivery service. Managed services
lower operational load but introduce vendor, data, and usage-cost risk. Each
integration must be enabled independently, server-side where secrets exist,
and remain non-authoritative for commerce actions.
