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

- Priority ordering moves by at most 10 points, and only when exactly one current observed profile in the workspace serves the parser. Two current observed profiles for one parser are ambiguous and have no effect. A profile that is not observed, or that is stale, never changes ordering, and never blocks a current one.
- Severe evidence gaps (critical or high) keep a priority floor of 70, so a historically useful source cannot suppress a critical missing signal.
- `apply_calibration_to_source_quality` can only lower a confidence multiplier, only for an observed profile of the same source and parser that is current at the `as_of` time it is given, and it never changes score, allowed or blocked signal types, freshness, or source type. Without an `as_of`, it has no effect. It is implemented but not yet on any production path; wiring it in is a separate, reviewed change. It is implemented but **not on the import path today**: record confidence is unchanged, and the bound is tested rather than live.
- Each profile reports its eligible and excluded counts, exclusion reasons, and a 95% Wilson interval for the positive share. The interval is descriptive only: it does not feed the adjustment, which is bounded by policy instead. Signals from one comparison are correlated, so the interval is optimistic.
- Import-quality facts (rejected rows, duplicate removal) are recorded for every resolvable import, even without a comparison, but are excluded from the adjustment. Evidence quality belongs to the normalizer and source-quality scorer, not to calibration.
- A comparison counts as a single-source change only when its baseline and current discoveries together name one source. A source dropped between the two is treated as a confound.
- Staleness is 90 days before the reference time. The reference is the newest comparison, unless an internal `as_of` is given, so a workspace whose comparisons are all old is never marked stale by its own clock.
- Only the 500 most recently registered comparisons are read (registration order, not timestamps). The run says so when the window is full, even when an `as_of` later filters it. Repeated ids in a request count once; unknown and foreign ids are recorded as exclusions.
- A run scoped to `comparison_ids` or `import_ids` is recorded, and its summary says its profiles do not change ordering. It does not replace the workspace profiles that drive recommendations.
- A workspace run retires any profile and any current signal whose evidence has dropped out, so neither a stale profile nor a listed signal can outlive its comparison. A workspace run with no comparisons in view keeps the existing state: an empty or reset upstream must not erase it.
- Run records are capped at the 50 most recent, so state does not grow without bound.
- A profile is judged against the plan's own time. It is ignored when the plan is more than 90 days after its last eligible evidence, and also when its evidence is dated after the plan. The reason is recorded as `stale_profile` or `profile_after_plan_time`.
- If the state file cannot be written, the run is recorded as `persisted: false` with status `partial`, and it reports no profiles. The in-memory state is rolled back in the same step, so ordering never uses profiles that were not saved.
- Duplicate source names are checked with an exact query per source, so a clash is found however many other imports exist.
- A recommendation plan's identifier includes the calibration that was applied and the resulting priorities, so a rebuilt plan with different content has a different identifier and does not replace the earlier one.
- Registry reads and writes are serialized within a process, so a read never sees a write in progress, and concurrent runs cannot discard each other's committed records. Separate processes sharing one state file are not coordinated; keep one writer per state file.

## Determinism

Signal, profile and run identifiers are derived from their content, and the run timestamp is the newest comparison's time, never the wall clock. The reference time can be set with an internal `as_of` argument, which also bounds which imports are visible; the API does not expose it. A replay at a fixed `as_of` therefore gives the same result after later evidence arrives. Identical inputs give identical output. A repeated run overwrites its records instead of accumulating them. A run over no comparisons is dated at 0 (the epoch), because there is nothing to date it by.

## Stored state

Corrupt content, including bytes that are not UTF-8, is moved to `<name>.unreadable-<n>` before the next write, with a new number each time, so earlier copies are kept. A read error (for example, a permissions problem) is not treated as corruption: the file is left alone and writes are refused until it can be read. Records written before this policy, including those nested inside stored runs, load as `legacy_unverified` with neutral adjustments, so they cannot drive ordering until a new run replaces them.

All calibration remains local/cache-only. No network, credentials, scraping, live connector, commerce, advertising, payment, or publication path is enabled.

Rollback: revert the commit. Records written by this policy stay readable by the earlier code, which ignores the new fields.
