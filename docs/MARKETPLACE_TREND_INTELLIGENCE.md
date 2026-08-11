# Offline Marketplace Trend Intelligence

MarketOS now has a bounded, offline-first layer for adding marketplace-native
demand and pricing signals to consulting research. It is deliberately separate
from supplier evidence: an Amazon bestseller, a Terapeak manual import, or a
Mercado Libre trend snapshot can support a demand hypothesis, but none proves
that a supplier has stock, a usable cost, shipping, or permission to sell.

## What is implemented

The normalization model supports Amazon, eBay, Mercado Libre, Alibaba,
AliExpress, Etsy, Walmart, Shopify storefront snapshots, and WooCommerce
storefront snapshots. The current adapters accept only sanitized local JSON and
CSV. Supported JSON shapes include a list of records and an object containing
`records`, `items`, `products`, `results`, or `offers`.

Supported offline sources include bestseller snapshots, product snapshots,
manual eBay/Terapeak exports, trend/highlight snapshots, high-profit editorial
selections, and storefront snapshots. Every normalized record includes:

- field-level provenance (`fixture`, `manual_import`, `observed`, `derived`,
  `unavailable`, `malformed`, or `blocked`);
- price, review, rating, rank, seller, offer, shipping, and fulfillment hints;
- source confidence and deterministic warnings;
- `read_only=true`, `network_calls=false`, and `mutated=false` safety flags.

The scoring model reports demand proxy, marketplace opportunity, price
confidence, source diversity, saturation, and an explicit next recommendation.
It always keeps `validate_supplier_first` available when supplier proof is not
present.

## Run the offline slice

```powershell
python scripts/run_marketplace_trend_intelligence.py --json
python scripts/run_marketplace_trend_intelligence.py --markdown
python scripts/run_marketplace_trend_intelligence.py `
  --candidate-seed tests/fixtures/marketplace_trends/amazon_best_sellers_snapshot.json `
  --json
python scripts/run_marketplace_trend_intelligence.py `
  --manual-import tests/fixtures/marketplace_trends/ebay_terapeak_import.csv `
  --json
python scripts/run_marketplace_trend_intelligence.py `
  --output artifacts/marketplace_trends/latest `
  --markdown
```

The default command performs no network I/O and writes no files. `--output`
creates only `marketplace_trend_report.json`, `marketplace_trend_report.md`,
and `marketplace_source_summary.json`. The optional `--allow-network` flag is
intentionally rejected by this first offline slice; use the existing bounded
public-market harness for an explicitly approved public-page experiment.

## Feeding consulting reports

Generate the existing Product Validation Report with the sanitized trend report:

```powershell
python scripts/run_marketplace_trend_intelligence.py `
  --output artifacts/marketplace_trends/latest `
  --markdown
python scripts/generate_product_validation_report.py `
  --marketplace-trend-report artifacts/marketplace_trends/latest/marketplace_trend_report.json `
  --markdown
```

The client-facing report adds Marketplace Demand Signals, including the top
marketplace candidate, observed marketplaces, opportunity, and saturation. If
no trend report is supplied, it says `marketplace_trends_not_supplied` rather
than inventing evidence.

## Evidence interpretation

Marketplace evidence can answer:

- whether a candidate appears across more than one marketplace;
- whether a product has bestseller/rank or rising-trend signals;
- whether public price bands and review density are worth investigating;
- whether saturation and source diversity make the next validation worthwhile.

It cannot answer without supplier evidence:

- landed cost or margin;
- inventory or variant availability;
- shipping cost or delivery time;
- authorization, compliance, or fulfillment feasibility.

Recommendations are therefore validation guidance, not profit forecasts or
launch authorization. A strong public signal with no supplier proof should
normally produce `validate_supplier_first`.

## Safety boundaries

This layer does not log in, scrape paid dashboards, bypass CAPTCHAs, call
provider APIs, persist HTML, store raw provider responses, place orders, mutate
inventory, send customer messages, launch ads, or mutate Shopify/provider
systems. Manual imports must be sanitized by the operator before being placed
in a local working directory. Credentials and private client data never belong
in fixtures or reports.
