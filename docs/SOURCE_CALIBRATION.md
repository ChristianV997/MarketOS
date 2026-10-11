# Source Calibration

Source calibration summarizes how local evidence sources have behaved in recorded discovery comparisons. It is deterministic, bounded, and non-causal.

## What it can infer

Calibration can record that, after a source was included, the evidence count increased, a category score/rank changed, a recommendation changed, or an import produced duplicate/rejected/low-confidence evidence. It can use those observations to adjust future import recommendation priority within bounded limits.

## What it cannot infer

It cannot prove that a source caused an opportunity to improve, prove market demand, prove profitability, or upgrade a blocked/live source. Ambiguous multi-source comparisons, unmatched or stale comparisons, and comparisons without a recorded baseline are excluded from adjustments; they stay in the run as counted, descriptive records.

## Workflow

1. Import local evidence.
2. Run category discovery.
3. Run refinement and create recommended templates.
4. Import a recommended dataset.
5. Run `import-refine-compare` against a baseline discovery.
6. Run `POST /api/discovery/source-calibration`.
7. Run refinement again. Only profiles with status `observed` change recommendation priority, and only within the bounds below.

## Evidence status and bounds

A profile is `observed` only with at least 3 eligible signals across at least 2 distinct single-source comparisons. Otherwise it is `limited` (or `no_eligible_signals`) and neutral: its priority adjustment is 0 and its confidence multiplier is 1.0.

- Priority ordering moves by at most 10 points, and only when the parser has exactly one observed profile in the workspace. Two sources for one parser are ambiguous and have no effect.
- Severe evidence gaps (critical or high) keep a priority floor of 70, so a historically useful source cannot suppress a critical missing signal.
- `apply_calibration_to_source_quality` can only lower a confidence multiplier. It never changes score, allowed or blocked signal types, freshness, or source type, so a fixture or manual source cannot be upgraded to live.
- Each profile reports its eligible and excluded counts, exclusion reasons, and a 95% Wilson interval for the positive share. Signals from one comparison are correlated, so that interval is optimistic.
- Excluded comparisons are those more than 90 days older than the newest comparison (or an explicit `as_of`), those whose baseline is missing, and those from another workspace.

## Determinism

Signal, profile and run identifiers are derived from their content, and the run timestamp is the newest comparison's time, never the wall clock. The reference time can be set with an internal `as_of` argument; the API does not expose it. Identical inputs give identical output. A repeated run overwrites its records instead of accumulating them.

All calibration remains local/cache-only. No network, credentials, scraping, live connector, commerce, advertising, payment, or publication path is enabled.

Rollback: revert the commit. Profiles saved before this policy load with neutral defaults and have no ordering effect.
