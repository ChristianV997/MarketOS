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

Supplier feasibility is the natural add-on to the evidence scan: it turns a
marketplace demand hypothesis into a sourcing-risk conversation. Keep the
landed-cost scenario and break-even CPA/ROAS visibly labeled as assumptions
unless the underlying supplier fields are observed through an approved
read-only source.

Consumer attention is the next report module. Use sanitized review, search,
comment, and creative snapshots to show a client the language customers use,
the strongest product hooks, likely objections, and a bounded set of UGC
formats to test. Sell this as creative-research evidence, not as a promise of
ad performance. The recommended delivery sequence is marketplace demand,
supplier feasibility, consumer attention, then a human-reviewed launch draft.

## Premium report offer

Product Opportunity Synthesis v1 is the premium decision layer for a
$500–$1,000 consulting report. It fuses the three evidence pillars, shows a
confidence grade and risk profile, provides price and break-even scenarios, and
ends with one next action plus a fourteen-day validation plan. The client buys
clarity and prioritization, not a profit guarantee.

Run the synthesis before generating the client report. Review all fixture and
manual labels and assumptions manually; never present a fixture supplier cost
or planning CPA threshold as live proof.
