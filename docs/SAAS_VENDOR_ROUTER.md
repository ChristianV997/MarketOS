# SaaS Capability Router

## Purpose

MarketOS is the evidence, planning, and orchestration layer—not a replacement
for every commerce, research, creative, support, hosting, or automation SaaS.
The capability router extends the existing `backend.providers.ProviderRegistry`
with deterministic metadata for choosing a vendor, owner, integration mode,
approval boundary, and MVP stage. It does not create clients, store credentials,
call vendors, schedule work, or authorize an external action.

## Architecture

- `backend/providers/registry.py` remains the authoritative static ProviderRegistry.
- `backend/providers/vendor_catalog.py` maps provider IDs to capability records;
  it does not register duplicate vendor clients.
- `backend/providers/vendor_router.py` chooses a safe route deterministically.
- `backend/providers/connector_contracts.py` defines the evidence, fixtures,
  rollback, and approval requirements required before a real integration.
- `backend/workspaces/org_chart.py` maps the metadata to human-owned workspace
  departments and advisory roles. It is not an autonomous agent runtime.

## Routing policy

For the MVP, routing prefers: use-now records, managed SaaS where it removes
infrastructure burden, existing safe adapters, no-auth/read-only/manual-export
mode, and no live-mutation capability. A vendor that can write externally is
never selected in MVP mode. `evaluate_next` means catalog/contract work only;
`defer` means no default route is selected.

| Capability area | Use now | Evaluate next | Defer |
|---|---|---|---|
| Durable MVP data | Supabase schema/optional server adapter | Neon alternative | Postgres migration |
| Hosting | Vercel frontend; Railway or Render API | Fly.io | bespoke platform |
| Edge + observability | Cloudflare, PostHog, Sentry | Upstash/QStash, Resend | autonomous notifications |
| Public research | Google News RSS | trendspyg/manual product tools | credentialed scraping/data APIs |
| Commerce | Shopify catalog/read-only reference | Zendrop/CJ/AutoDS read-only contracts | fulfillment/order APIs |
| Creative + pages | Creatify/HeyGen, PageFly/GemPages manual packets | Webflow/Framer/Runway | automatic publishing |
| Support | Tidio/Manychat playbook exports | HubSpot/Gorgias | automated customer messages |
| AI routing | none activated | Cloudflare AI Gateway, Vercel AI Gateway, OpenRouter | global runtime router |

All pricing statuses are qualitative. Vendor records link to official product
pages captured on 2026-08-09; **verify current pricing, data policy, license,
and terms before committing spend.** No source URL implies an approval to call
or purchase a service.

## Capability taxonomy and ownership

Each capability carries an owning department, role, risk level, event types,
approval policy, MVP allowance, and forbidden actions. Departments are CEO /
Executive, Strategy + Risk, Market Research, Ecommerce Operations, Creative
Production, Sales + Support, Automation + Integrations, Data + Evidence, and
AI Ops. Every department is constrained from spend, publish, send, order,
payment, refund, fulfillment, launch, and provider mutation.

## Connector contracts

Available contract shapes are manual export, CSV import, read-only API, write
API requiring approval, MCP tool, embedded app, gateway, and sidecar. Every
contract declares inputs, outputs, canonical events, required fixtures, docs,
forbidden actions, and rollback. Priority contracts cover Google News RSS,
Supabase canonical events, Shopify read-only imports, Zendrop MCP (read-only
scope), AutoDS monitoring, Creatify/HeyGen briefs, PageFly/GemPages packets,
Tidio/Manychat playbooks, Pipedream references, QStash evaluation, and model
gateway evaluation.

## CLI

```powershell
python scripts/vendor_capability_report.py --stage mvp --json
python scripts/vendor_capability_report.py --stage mvp --markdown
python scripts/vendor_capability_report.py --capability video_ad_generation --json
python scripts/vendor_capability_report.py --output artifacts/vendor-capability-report.json --json
```

The CLI is read-only unless `--output` is explicitly supplied. Output remains
under `artifacts/`; it makes no network or provider call.

## Relationship to MVP Island and public signals

The MVP Island continues to use its bounded Google News RSS flow only when an
operator explicitly opts into a network read. Its `public_signal_observed`
canonical events stay advisory and cannot prove demand, profitability,
launch-readiness, or spend authorization. Supabase remains an optional,
server-only canonical EventRepository target—not the default repository.

The [Commerce MVP Vertical Slice](COMMERCE_MVP_VERTICAL_SLICE.md) consumes
these router recommendations as packet metadata. It does not activate a
connector or convert a recommendation into external authority.

## Promoting a vendor

Before moving a catalog/manual/export route to API or MCP use: add a connector
contract, source attribution, mocked/fixture tests, canonical-event mapping,
credential scope, explicit write approval if relevant, deterministic rollback,
and a review of live-mode safety. The router itself must remain policy metadata;
real adapter implementations belong at the existing integration boundary.

## Open-source reuse

The router uses standard-library dataclasses and local patterns; it copied no
third-party code and adds no dependency. Open-source options are cataloged only
with license status. GPL/AGPL or internal-only tools are not default
client-facing MVP choices without explicit legal review.
