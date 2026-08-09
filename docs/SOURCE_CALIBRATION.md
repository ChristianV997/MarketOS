# Source Calibration

Source calibration summarizes how local evidence sources have behaved in recorded discovery comparisons. It is deterministic, bounded, and non-causal.

## What it can infer

Calibration can record that, after a source was included, the evidence count increased, a category score/rank changed, a recommendation changed, or an import produced duplicate/rejected/low-confidence evidence. It can use those observations to adjust future import recommendation priority within bounded limits.

## What it cannot infer

It cannot prove that a source caused an opportunity to improve, prove market demand, prove profitability, or upgrade a blocked/live source. Ambiguous multi-source comparisons receive lower confidence and remain descriptive.

## Workflow

1. Import local evidence.
2. Run category discovery.
3. Run refinement and create recommended templates.
4. Import a recommended dataset.
5. Run `import-refine-compare` against a baseline discovery.
6. Run `POST /api/discovery/source-calibration`.
7. Run refinement again so bounded calibration adjustments appear in recommendations.

Profiles begin at usefulness 50 and receive deterministic bounded adjustments. Severe evidence gaps retain a high-priority floor, so a historically useful source cannot suppress a critical missing signal.

All calibration remains local/cache-only. No network, credentials, scraping, live connector, commerce, advertising, payment, or publication path is enabled.
