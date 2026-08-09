# Replay Certification Foundation

For read-only evidence classification of financially material shadow features, see [Shadow Feature Evaluation](SHADOW_FEATURE_EVALUATION.md). It builds on canonical replay fixtures without changing feature flags or production behavior.

The first default-off writer compatibility proof is documented in [Event Migration Pilot](EVENT_MIGRATION_PILOT.md). Its canonical records are replayed only for parity certification; legacy workflow JSONL remains authoritative.

Canonical `public_signal_observed` fixture events are also replay-certified. See [Public Signal Ingestion](PUBLIC_SIGNAL_INGESTION.md); public observations remain advisory and have no launch or spend authority.

This foundation validates deterministic, synthetic canonical event fixtures before any production writer migration. It is read-only and does not execute workflows, integrations, feature flags, or providers.

Fixtures under `tests/fixtures/golden_replay/` cover workflow transitions, ledger economics, financial shadow evidence, advisory intelligence containment, and a compact mixed dry-run chain. `backend.events.replay_certification` validates ordering, calculates stable hash sequences, summarizes workflow/ledger/shadow/advisory records, and rejects advisory live authority.

Financial projection is certification-only: it sums synthetic recorded revenue, cash, supplier cost, ad spend, refunds, and reconciles duplicate attribution claims by order ID. It deliberately does not replace production ledger projections.

The shadow classifier permits `PROMOTE` only with a sufficient sample, non-regressive primary and safety metrics, and no safety blocker. It defaults to `KEEP_SHADOW`; blockers return `REWORK`. It never changes a feature flag.

Run `python scripts/event_migration_readiness.py --fixtures` for JSON readiness output. Use `--output artifacts/event-migration-readiness.json` only to write a report artifact. Future changes must add stable synthetic fixtures and expected summaries before migrating a writer behind `EventRepository`.

This supports eventual legacy migration but does not migrate workflow JSONL, replay store, ledger readers, or shadow writers.
