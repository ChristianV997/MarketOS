# Product Validation Report Pack

Generate a client-ready, read-only consulting report from existing MarketOS evidence:

```powershell
python scripts/generate_product_validation_report.py --client-name "Demo Client" --markdown
python scripts/generate_product_validation_report.py --output artifacts/product_validation_report/latest --markdown
```

The report is validation guidance, never a profit promise or launch authority.
Fixture/demo evidence is clearly labeled and must be replaced with sanitized
live supplier evidence before any commercial launch decision.

## Optional marketplace trend enrichment

Marketplace-native demand signals can be generated offline and passed into the
same report pack:

```powershell
python scripts/run_marketplace_trend_intelligence.py `
  --output artifacts/marketplace_trends/latest `
  --markdown
python scripts/generate_product_validation_report.py `
  --marketplace-trend-report artifacts/marketplace_trends/latest/marketplace_trend_report.json `
  --markdown
```

The report adds Marketplace Demand Signals and labels the evidence mode. These
signals improve demand/competition context but never become supplier proof.
Price, inventory, shipping, and margin claims remain blocked or provisional
until a read-only supplier source observes them.

## Optional supplier feasibility enrichment

Supplier feasibility can be added independently of authenticated CJ access:

```powershell
python scripts/run_supplier_feasibility_intelligence.py `
  --output artifacts/supplier_feasibility/latest `
  --target-sell-price 29.99 `
  --markdown
python scripts/generate_product_validation_report.py `
  --supplier-feasibility-report artifacts/supplier_feasibility/latest/supplier_feasibility_report.json `
  --markdown
```

The report distinguishes supplier cost, landed cost, delivery, inventory, and
margin scenarios from marketplace selling prices. Fixture/manual evidence is
clearly labeled and does not replace live read-only supplier proof.

## Optional consumer attention enrichment

Consumer attention evidence adds a third consulting signal: whether a product
has understandable hooks, pain points, objections, and demonstrable creative
angles. It is offline/manual by default and does not authorize ad spend or
content publishing.

```powershell
python scripts/run_consumer_attention_intelligence.py --output artifacts/consumer_attention/latest --markdown
python scripts/generate_product_validation_report.py `
  --marketplace-trend-report artifacts/marketplace_trends/latest/marketplace_trend_report.json `
  --supplier-feasibility-report artifacts/supplier_feasibility/latest/supplier_feasibility_report.json `
  --consumer-attention-report artifacts/consumer_attention/latest/consumer_attention_report.json `
  --markdown
```

The report adds Consumer Attention Signals, Search and Trend Signals, Ad and
Creative Evidence, Voice of Customer / Pain Points, Objections and Risk
Signals, Recommended Hooks and UGC Angles, Creative-Market Fit, and Consumer
Source Confidence. Missing input is reported as
`consumer_attention_not_supplied`.

## Consulting Report v2: Product Opportunity Synthesis

Fuse the three sanitized reports into the premium decision layer:

```powershell
python scripts/run_product_opportunity_synthesis.py `
  --marketplace-trend-report artifacts/marketplace_trends/latest/marketplace_trend_report.json `
  --supplier-feasibility-report artifacts/supplier_feasibility/latest/supplier_feasibility_report.json `
  --consumer-attention-report artifacts/consumer_attention/latest/consumer_attention_report.json `
  --output artifacts/opportunity_synthesis/latest `
  --markdown
python scripts/generate_product_validation_report.py `
  --opportunity-synthesis-report artifacts/opportunity_synthesis/latest/opportunity_synthesis_report.json `
  --markdown
```

Report v2 adds Executive Decision, Opportunity Scorecard, Evidence Confidence
Matrix, Unit Economics and Break-Even Thresholds, Recommended Price Band,
Creative Hooks and Ad Angles, Top Risks and Blockers, Kill / Scale Rules,
Fourteen-Day Validation Plan, and Client Action Checklist. Thresholds are
planning assumptions, not observed ad performance or launch permission.
## Launch Draft Pack upsell

After generating a Product Opportunity Synthesis, create a draft-only launch asset package:

```powershell
python scripts/generate_launch_draft_pack.py --markdown
```

The pack adds an offer stack, listing, landing-page structure, creative briefs, UGC plans, FAQ copy, and draft-only Shopify/Medusa payloads. Feed its summary back into this report with `--launch-draft-pack`; the report shows status, creative-test count, UGC count, payload draft status, and approval blockers without embedding the full asset package.

This is consulting work product, not launch authorization. It does not publish, launch ads, spend money, create orders, send messages, or call storefront APIs.

## Website / Store / Funnel Draft Summary

Pass `--site-draft-pack` to include a compact summary of site type, route count, CMS model count, platform payload availability, SEO/analytics status, conversion-test count, deployment blockers, and approval blockers. The full blueprint remains a separate export.
