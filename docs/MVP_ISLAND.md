# MarketOS MVP Island

## Objective

The MVP Island is a deployable, intentionally narrow MarketOS surface:

```text
manual public/no-auth signal read -> canonical event -> optional Supabase row
-> dry-run opportunity/unit-economics/advisory artifact -> API/dashboard read
-> manual export and human approval
```

It makes the useful evidence and planning loop deployable without promoting the
repository's experimental, provider-mutating, or autonomous loops.

## ON in the MVP Island

- Explicitly invoked public RSS signal ingestion, fixture/cache mode by default.
- Canonical `Event` creation and local JSONL event persistence.
- Optional, explicit Supabase canonical-event persistence when configured.
- Existing dry-run opportunity, unit-economics, validation, and advisory output.
- Existing FastAPI read views and Vite dashboard deployment.
- Manual export, review, and approval.
- Optional error/usage telemetry when the operator configures it.

## OFF in the MVP Island

- Live ad launch or spend, Shopify mutation, supplier ordering, payments,
  fulfillment, customer communications, and publishing.
- Autonomous budget/capital mutation and every `*_LIVE` shadow promotion flag.
- Background full-orchestrator loop, scheduled signal ingestion, and durable
  queue execution.
- DAO/future packages, unconfigured heavy vector memory, and experimental
  modules not named by the profile.

`deploy/mvp/marketos.mvp.json` is the machine-readable contract. Its guard in
`backend/runtime/mvp_mode.py` is fail-closed for unlisted actions; it does not
rewrite or silently control legacy runtimes.

## Deployment topology

| Concern | Fast MVP recommendation | Responsibility |
| --- | --- | --- |
| Frontend | Vercel | Vite static hosting, previews, CDN |
| API | Railway or Render | FastAPI container/process, `/health`, `/ready` |
| Durable MVP data | Supabase | Postgres, future Auth/Storage target |
| Edge/DNS | Cloudflare | DNS/CDN/WAF; no backend rewrite required |
| Queue/schedule | Deferred; evaluate Upstash QStash | Manual invocation first |
| Product analytics | Existing default-off PostHog | Opt-in telemetry only |
| Error tracking | Existing default-off Sentry | Opt-in server error capture |
| Transactional email | Deferred Resend | Human-approved reports only |

No SaaS configuration is activated by this repository change. Verify current
pricing, data residency, terms, and security controls before an operator adds
credentials.

## Manual approval and real-signal policy

Real public RSS reads require two deliberate choices: the caller must invoke
the public-signal CLI/API path and pass the explicit network opt-in. The MVP
profile never schedules them. A signal is attributed, source-local evidence;
it does not prove demand, margin, market size, ROAS, conversion, or launch
readiness.

Manual approval is still required before exporting a report to a customer or
using an advisory recommendation outside the product. No artifact may authorize
promotion, publishing, spend, fulfillment, payment, or a provider mutation.

## What “running” means

A running MVP has a healthy FastAPI process, an optional Vercel dashboard, a
loaded profile, all live commerce flags disabled, and a deterministic path to
preview or manually ingest public signals. If Supabase is configured, its
canonical-event adapter can be explicitly constructed by a future wiring PR;
the JSONL repository remains the default today.

The [SaaS Capability Router](SAAS_VENDOR_ROUTER.md) is the metadata-only
companion that assigns MVP capabilities to managed vendors and human-owned
departments. It never activates a vendor integration or changes dry-run policy.

The [Commerce MVP Vertical Slice](COMMERCE_MVP_VERTICAL_SLICE.md) composes the
existing public-signal, event, and routing foundations into a manual-review
packet without creating any external commerce object.

Its optional [Shopify Read-only Import](SHOPIFY_READONLY_IMPORT.md) accepts a
local export only; it is not an authenticated or write-capable Shopify path.

[Supabase canonical-events staging](SUPABASE_CANONICAL_EVENTS_STAGING.md) is
also opt-in and server-only; it keeps JSONL as the default output.

## Promotion gates

Promote one capability at a time only after: schema/RLS review; adapter tests
with a real staging project; canonical replay compatibility; explicit owner and
rollback plan; provider-specific dry-run tests; human approval; and a decision
to accept current SaaS cost and lock-in. Deferred capabilities include Supabase
Auth workspace policies, browser write paths, queues/schedulers, live commerce,
and any automatic decision execution.

Run `python scripts/mvp_readiness.py --json` locally before deployment. It is
read-only and reports configuration gaps without calling any provider.
