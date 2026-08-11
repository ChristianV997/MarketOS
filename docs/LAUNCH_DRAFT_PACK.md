# Launch Draft Pack v1

Launch Draft Pack is the first consulting upsell after Product Opportunity Synthesis. It converts the existing marketplace, supplier-feasibility, consumer-attention, and unit-economics evidence into a human-reviewable asset package:

- offer stack and price-band guidance;
- product listing and landing-page drafts;
- five ad-angle concepts, hooks, short scripts, and static concepts;
- three UGC briefs and a creative test matrix;
- FAQ/objection copy;
- Shopify- and Medusa-shaped payloads that are always `draft`;
- approval checklist and risk review.

It is a presentation layer, not a fourth evidence engine. It never publishes, spends, posts, creates orders, collects payments, sends customer messages, or calls Shopify/Medusa.

The next optional upsell is `scripts/generate_site_draft_pack.py`, which consumes this pack and produces a platform-neutral route/CMS/SEO/analytics blueprint for ecommerce, service, catalog, and funnel clients.

## Generate it

Default mode uses the repository's sanitized fixture reports and performs no network I/O:

```powershell
python scripts/generate_launch_draft_pack.py --json
python scripts/generate_launch_draft_pack.py --markdown
```

Use a synthesis report and optional client context:

```powershell
python scripts/generate_launch_draft_pack.py `
  --opportunity-synthesis-report artifacts/opportunity_synthesis/latest/opportunity_synthesis_report.json `
  --client-context tests/fixtures/launch_draft_pack/client_context.json `
  --output artifacts/launch_draft_pack/latest `
  --markdown
```

The output directory contains only sanitized JSON/Markdown drafts. No credentials, raw payloads, HTML, cookies, or browser traces are accepted.

## Review boundary

Every pack is `draft_only_pending_human_approval`. Unknown SKU, stock, weight, dimensions, certifications, shipping, and policy fields remain `TBD`. The Shopify and Medusa payloads have `status: draft`, and their metadata explicitly says that launch is not authorized.

Before any future activation, a human must confirm supplier proof, landed cost, delivery, inventory, returns, claims, price band, break-even assumptions, budget cap, creative claims, and the storefront draft. Fixture/manual evidence can justify a validation brief; it cannot authorize launch.

## Consulting use

Sell this as the practical upsell after a Product Validation Report: the report answers whether a candidate merits further work; the Launch Draft Pack gives the client a coherent offer, page, creative, and review checklist without pretending that publishing or ad spend is complete. A later Launch Copilot may execute approved steps, but that is outside v1.
## CompanyOS handoff

Launch Draft Pack outputs can be linked into CompanyOS as a delivery workstream and approval subject. This creates a manager brief and handoff checklist without publishing, sending, spending, or mutating Shopify/Medusa.
