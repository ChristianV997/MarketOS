# Consulting Revenue Playbook

MarketOS can now package a first-pass product validation report without
credentials or live provider access. The offline marketplace trend layer makes
the report more useful by triangulating bestseller, rank, review, pricing,
seller-density, and fulfillment signals across sanitized marketplace snapshots
and seller-provided manual imports.

## Offer structure

1. **Evidence scan** — a fixed-scope report using public, fixture, and manual inputs.
2. **Supplier proof add-on** — one bounded, credential-safe read-only supplier
   validation when the client/operator supplies access server-side.
3. **Launch-draft pack** — only after supplier cost, availability, shipping, and
   competitor evidence are sufficiently observed.

The report generator currently suggests a `$250-$750` starting range for the
report itself. Treat that as an internal pricing prompt, not an automatic quote;
scope, market, and client context still require human review.

## Client-safe claims

Sell clarity, not certainty: “we found a demand/pricing hypothesis and show the
next validation step.” Do not promise profit, product-market fit, supplier
authorization, or launch readiness from marketplace trends alone. Keep
`fixture_demo`, `manual_import`, and live-observed evidence visibly separate.

## Repeatable delivery

```powershell
python scripts/run_marketplace_trend_intelligence.py `
  --manual-import .\client-sanitized\marketplace.csv `
  --output artifacts/marketplace_trends/client-review `
  --markdown
python scripts/generate_product_validation_report.py `
  --marketplace-trend-report artifacts/marketplace_trends/client-review/marketplace_trend_report.json `
  --output artifacts/product_validation_report/client-review `
  --markdown
```

Review the Markdown manually before sharing. Remove client-identifying context
from fixtures and never commit generated artifacts or raw exports.
