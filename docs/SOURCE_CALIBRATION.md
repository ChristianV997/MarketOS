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

- Priority ordering moves by at most 10 points, and only when exactly one observed profile in the workspace serves the parser. Two observed profiles for one parser are ambiguous and have no effect. A profile that is not observed never changes ordering, and never blocks an observed one.
- Severe evidence gaps (critical or high) keep a priority floor of 70, so a historically useful source cannot suppress a critical missing signal.
- `apply_calibration_to_source_quality` can only lower a confidence multiplier, and it never changes score, allowed or blocked signal types, freshness, or source type. It is implemented but **not on the import path today**: record confidence is unchanged, and the bound is tested rather than live.
- Each profile reports its eligible and excluded counts, exclusion reasons, and a 95% Wilson interval for the positive share. Signals from one comparison are correlated, so that interval is optimistic.
- Import-quality facts (rejected rows, duplicate removal) are recorded per source but are excluded from the adjustment. Evidence quality belongs to the normalizer and source-quality scorer, not to calibration.
- A comparison counts as a single-source change only when its baseline and current discoveries together name one source. A source dropped between the two is treated as a confound.
- Staleness is 90 days before the reference time. The reference is the newest comparison, unless an internal `as_of` is given, so a workspace whose comparisons are all old is never marked stale by its own clock.
- Only the 500 most recent comparisons are read. The run says so when the window is full.
- A run scoped to `comparison_ids` or `import_ids` is recorded, but it does not replace the workspace profiles that drive recommendations.
- If the state file cannot be written, the run reports `persisted: false` and status `partial`, and it says it cannot be retrieved later by its identifier.

## Determinism

Signal, profile and run identifiers are derived from their content, and the run timestamp is the newest comparison's time, never the wall clock. The reference time can be set with an internal `as_of` argument; the API does not expose it. Identical inputs give identical output. A repeated run overwrites its records instead of accumulating them. A run over no comparisons is dated at 0 (the epoch), because there is nothing to date it by.

## Stored state

An unreadable state file is moved to `<name>.unreadable` before the next write, so its contents are kept. Records written before this policy load as `legacy_unverified` with neutral adjustments, so they cannot drive ordering until a new run replaces them.

All calibration remains local/cache-only. No network, credentials, scraping, live connector, commerce, advertising, payment, or publication path is enabled.

Rollback: revert the commit. Records written by this policy stay readable by the earlier code, which ignores the new fields.
