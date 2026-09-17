# MarketOS Mission 7 — Integration, Replay & Release Evidence

Machine-readable evidence: [`MARKETOS_INTEGRATION_EVIDENCE_MISSION7.json`](./MARKETOS_INTEGRATION_EVIDENCE_MISSION7.json).

This is an **integration evidence consumer**, not a second quality gate: it
records what was actually run and found, classified as `actual` /
`simulated` / `fixture` / `unavailable` / `not_run` / `failed` / `malformed`
/ `blocked`. It does not itself pass/fail a build.

## What this mission did

- Refreshed and recorded the actual head SHAs of PRs #211, #221, #223–#231,
  #237–#240 rather than trusting PR descriptions (see the JSON's
  `tested_heads`).
- Confirmed `evaluation/commerce/commerce_operations_cycle.py` — the single
  composed dry-run cycle the mission brief assumes exists — is **not on
  `origin/main`**; it exists only on the unmerged, mutually-independent PR
  #225 and its two siblings (#238, #239). See `architecture_findings`.
- Built a cross-system integration matrix (`tests/system/test_marketos_dry_run_integration_matrix.py`,
  5 scenarios) composing `opportunity_synthesis`, `product_validation_report`,
  the Resource & Execution Governor, and the TrustOS gate — using only
  existing public builders, per "do not create a second workflow engine."
- Added 9 composed negative/security assertions
  (`tests/system/test_marketos_negative_security_assertions.py`).
- Added a deterministic replay harness
  (`tests/system/test_marketos_deterministic_replay.py`) proving canonical
  JSON equality, event-count/replay-hash stability, stable ordering, and
  idempotent re-append across two runs of the same scenario.
- Reproduced and fixed **two genuine production defects** (see
  `defects_found_and_repaired` in the JSON):
  1. `evaluation/economics.py` silently mixed currencies (e.g. an MXN
     supplier quote against a USD sell price) into a wrong-by-an-order-of-
     magnitude contribution figure. Now fails closed with `currency_mismatch`.
  2. `evaluation/commerce/product_validation_report.py` passed
     credential-shaped strings from upstream evidence straight through into
     the client-facing report. It now routes the composed summary through
     the existing (already-merged) TrustOS `check_workspace_leakage()`
     detector and redacts matches — no new detection authority was created.
- Verified (no defect) that `validate_event_sequence()`'s duplicate/
  non-monotonic/missing-workspace checks work correctly; only test coverage
  was missing, not correctness.
- Ran the full repository suite: **7047 passed, 4 skipped, 0 failed**
  (255.58s), plus targeted TrustOS/Governor/Approval-Ledger/architecture-
  boundary suites (1180 passed) and every new/changed file (73 passed).
  `ruff` and `compileall` clean on every touched line; `git diff --check`
  clean.

## What was not run, and why

See `omitted_or_not_run` in the JSON — in short: the full
`run_local_quality_gate.py` changed-scope classifier (needs CI-history
context this fresh environment doesn't have), live checkout/execution of
the other open PR branches (read their diffs/descriptions instead, and did
**not** count that as execution evidence), GitHub Actions status (not
queried — this report never claims GitHub-green from local tests), and
mission scenarios F/G (no service-client value/capacity module exists
anywhere in this repository — reported as an architecture gap, not
fabricated).

## Readiness

`dry_run_integration_tested_not_live_validated`. Not merged.
