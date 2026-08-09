# Event Writer Migration Checklist

Use this checklist for every future EventRepository writer pilot.

- [ ] Choose one non-live, low-blast-radius writer and document rejected candidates.
- [ ] Preserve the legacy write, path, payload, return values, and readers through the compatibility period.
- [ ] Keep the canonical mirror disabled by default or explicitly dependency-injected.
- [ ] Mark canonical records `migration_pilot`, `dual_write`, `dry_run`, and `non_authoritative`.
- [ ] Do not grant live authority or mutate flags, providers, commerce, payments, orders, publishing, or budgets.
- [ ] Build canonical events only through `backend/contracts/events.py` and append only through `backend/events/repository.py`.
- [ ] Make canonical mirror failures observable but fail-open toward the authoritative legacy path.
- [ ] Add deterministic legacy input, expected canonical output, disabled, and failure fixtures.
- [ ] Compare event type, aggregate, workspace, correlation/causation, payload, metadata, ordering, and replay hashes.
- [ ] Add focused disabled, enabled, failure, replay, CLI, and compatibility tests.
- [ ] Run replay certification, architecture boundaries, relevant existing tests, and `git diff --check`.
- [ ] Document default-off configuration, rollback, and the exact scope intentionally not migrated.
- [ ] Run the full suite before merging a production writer migration.

## Stop conditions

Stop the pilot and retain legacy-only operation when the canonical event lacks a stable aggregate identity, changes any legacy payload meaning, loses ordering, fails JSON-safe validation, cannot demonstrate dry-run/non-authoritative metadata, or introduces a path to provider authority. Do not compensate by weakening the comparator or changing production consumers. Record the mismatch as a migration blocker, add a regression fixture, and resolve it in the mapper before trying the same writer again.
