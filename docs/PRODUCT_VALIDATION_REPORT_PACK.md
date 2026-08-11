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
