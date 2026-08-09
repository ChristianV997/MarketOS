# Market Discovery Refinement

MarketOS refinement is a local, evidence-limited research workflow. It does not call live providers, scrape websites, place orders, publish content, or claim that synthetic evidence is real market data.

## Operator workflow

1. Run `POST /api/discovery/refinement-cycle` to inspect persisted evidence and discovery runs.
2. Review the prioritized gaps and generated templates under `data/import_templates/`.
3. Replace placeholder rows with documented local exports; do not add credentials or live connections.
4. Use `POST /api/discovery/import-refine-compare` to import, rerun category discovery, compare against a baseline, and generate the next gap plan.
5. Inspect `/api/discovery/gap-analyses`, `/api/discovery/import-plans`, and `/api/discovery/comparisons` or the optional Obsidian notes.

## Supported local imports

Google Trends, TikTok Creative Center, Amazon bestseller snapshots, Meta Ad Library, Reddit keyword exports, MercadoLibre snapshots, supplier catalogs, Shopify orders, Stripe payments, and generic market CSV files.

Each row retains source file, parser, row number, workspace, and provenance. Source quality restricts which signals are allowed. Own-store exports may support first-party sales evidence, but they do not establish general market demand.

Refinement cycles also generate source-specific acquisition plans and disabled connector stubs. See [Evidence Acquisition Playbooks](EVIDENCE_ACQUISITION_PLAYBOOKS.md).

Source usefulness can be calibrated from persisted comparisons; see [Source Calibration](SOURCE_CALIBRATION.md). Calibration is descriptive and does not establish causality.

## Safety model

Import paths are restricted to approved project roots and are capped by row/file limits. Missing or unsafe imports fail closed. All reports use cautious language: a score change between runs is a descriptive change in recorded evidence, not proof of causality or market improvement. External live sources remain blocked.

## Example API payload

```json
{
  "workspace_id": "default",
  "imports": [{
    "input_path": "tests/fixtures/evidence_imports/supplier_catalog_sample.csv",
    "parser_type": "supplier_catalog_csv",
    "source_name": "supplier_export"
  }],
  "baseline_discovery_id": "discovery_...",
  "max_categories": 10,
  "max_hypotheses": 20
}
```
