# Canonical EventRepository Foundation

MarketOS currently has local legacy event paths: `backend/events/log.py` over the runtime replay store, `backend/orchestration/event_store.py` over workflow JSONL, broker `EventEnvelope` records, and ledger/shadow/replay readers. They remain supported during migration.

## Canonical event

New event code should use `backend.contracts.events.Event`: stable ID, workspace, aggregate type/ID, event type, schema version, UTC epoch `occurred_at`, causation/correlation/experiment/actor fields, source, payload, and metadata. Epoch floats match existing workflow and replay records. Serialization uses sorted JSON keys and converts non-finite floats to `null`; `replay_hash()` hashes that canonical form.

## Repository API and adapters

`backend.events.repository.EventRepository` defines append, append_many, get, stream, replay, and tail. `InMemoryEventRepository` is deterministic and idempotent by event ID for tests. `JsonlEventRepository` is a local JSONL adapter that preserves append order and skips malformed/torn lines. It is not a distributed or Postgres store.

The optional Supabase adapter and the metadata-only vendor selection policy are
documented in [MVP Island](MVP_ISLAND.md) and [SaaS Capability Router](SAAS_VENDOR_ROUTER.md); neither changes the default JSONL repository.

The explicit staging-only validation and CLI path is documented in
[Supabase Canonical Events Staging](SUPABASE_CANONICAL_EVENTS_STAGING.md).

`LegacyWorkflowEventStoreAdapter` and `LegacyRuntimeReplayAdapter` normalize existing records read-only. They do not alter legacy writers, broker ownership, workflow JSONL, DuckDB/replay persistence, or external services.

## Narrow dual-write pilot

[`EVENT_MIGRATION_PILOT.md`](EVENT_MIGRATION_PILOT.md) documents the default-off, non-authoritative mirror for the `shadow_mode_decision` legacy journal. It preserves the legacy write and uses an injected repository only for compatibility proof; it is not a general writer migration.

## Canonical public observations

[`PUBLIC_SIGNAL_INGESTION.md`](PUBLIC_SIGNAL_INGESTION.md) documents a canonical-first, manually invoked public RSS ingestion pilot. It writes only explicitly requested advisory `public_signal_observed` events through `JsonlEventRepository`; it has no legacy writer to replace.

## MVP deployment target

The optional `backend.events.adapters.supabase.SupabaseEventRepository` maps
only canonical events to the MVP `canonical_events` table. It is explicit and
not the default repository; it does not migrate JSONL/DuckDB/event-store
writers. See [MVP_ISLAND.md](MVP_ISLAND.md) and
[`deploy/supabase/schema.sql`](../deploy/supabase/schema.sql).

## Future migration order

Golden replay certification is documented in [REPLAY_CERTIFICATION.md](REPLAY_CERTIFICATION.md). It validates fixture compatibility before any writer migration. Financial shadow evidence is evaluated read-only by [SHADOW_FEATURE_EVALUATION.md](SHADOW_FEATURE_EVALUATION.md); it never changes a flag or writer.

1. Create canonical event contract and adapters — this PR.
2. Migrate new code to EventRepository only.
3. Migrate workflow event writes behind an adapter.
4. Migrate ledger/projection reads to canonical stream.
5. Migrate shadow feature journaling to canonical events.
6. Create golden replay scenarios.
7. Add a Postgres adapter after JSONL/replay compatibility is proven.
8. Remove legacy direct appends only after a compatibility period.

This PR intentionally does not execute steps 2–8 broadly, make network calls, or change dry-run/live behavior.
