# Public-signal event identity across workspaces: design decision

**Status: proposed, awaiting review.** This change alters no persisted identity. It adds this note and five failing regression tests that reproduce the collision on `main`. Identity changes wait for the decision recorded here.

## Problem (verified in code and by reproduction)

Two workspaces that ingest the same public article for the same query get the same canonical `event_id`. One workspace's row or line then overwrites or hides the other's.

Why the IDs collide:
- `signal_identifier()` hashes `source, query, source_url, title`. It has no workspace input (`backend/signals/public_signal_models.py:23-25`).
- `public_signal_event()` sets `event_id = "event:" + signal_id` and carries `workspace_id` as a separate field (`backend/signals/public_sources.py:143`).

Where the collision lands:
- **Supabase, separate adapter instances.** This is the production pattern: `build_supabase_staging_repository()` builds a new adapter per call (`backend/events/adapters/supabase_staging.py:58`). `append` runs `upsert(..., on_conflict="event_id")` (`backend/events/adapters/supabase.py:77`), so the second workspace replaces the first workspace's row. In `deploy/supabase/schema.sql:14-16`, `event_id` is the primary key and `workspace_id` is an ordinary nullable column.
- **Supabase, same adapter instance.** The in-memory `_known_ids` check (`supabase.py:73-74`) returns `idempotent=True`, and nothing is written for the second workspace.
- **JSONL.** Dedupe runs by `event_id` across the whole file (`backend/events/repository.py:25-28`, inherited by `JsonlEventRepository`). The second workspace gets `appended=False, idempotent=True`, and no line is written.
- **The file is shared by configuration.** The API writes every workspace into one server path, `MARKETOS_EVENT_WRITE_JSONL_PATH` (`api/routes/commerce_mvp.py:67-72, 99, 147-149`). This reaches normal deployments, not only the CLI.

Reporting defects with the same root cause. Each one reports success for writes that did not happen:
- `append_public_signal_events` returns every ID it was given, not only the appended ones (`public_sources.py:153-155`). `scripts/ingest_public_signals.py:64` writes that list into `written_event_ids`.
- `api/routes/commerce_mvp.py:147-149` discards the `AppendResult`s and appends `"jsonl"` to `write_targets` unconditionally. `event_count` is the attempted count.
- `backend/mvp_commerce/public_run.py:303-305` does the same and reports `("injected_repository",)`.
- `scripts/run_commerce_mvp_slice.py:165-167, 174` and `scripts/import_shopify_readonly.py:34` follow the same pattern.

Certification does not catch it. `validate_event_sequence` checks duplicate IDs inside a file (`backend/events/replay_certification.py:21`), but the JSONL dedupe runs before the file exists. In the reproduction, a file holding only alpha's rows validated clean (`[]`) while beta's two observations were absent.

Scope of loss: only public-signal observations collide. A run-level reproduction (fixture RSS, two workspaces, one in-memory repository) gave beta 13 events, 11 persisted for beta, while `write_targets` still reported `injected_repository`. Commerce events are workspace-scoped and do not collide.

## What is deterministic today

- `observed_at` comes from the RSS `pubDate` (`public_sources.py:78`), not from ingestion time. For one article, the payload is identical across workspaces.
- The only workspace-specific fields are `workspace_id` and `metadata.cache_status`.
- `Event.replay_hash()` hashes `canonical_json()`, which includes both `event_id` and `workspace_id` (`backend/contracts/events.py:78-82`).

## Options

### (a) Put the workspace in the event ID

`event_id` derives from `(workspace_id, signal_id)`, for example a SHA-256 over the canonical JSON array `[workspace_id, signal_id]`, the same style as `signal_identifier`. `aggregate_id` stays `signal_id`, because `validate_public_signal_events` requires `payload.signal_id == aggregate_id` (`backend/signals/public_signal_reporting.py:66`). The primary key, the foreign keys and the schema do not change.

- **Replay and determinism.** New rows get a different `event_id`, so a different `replay_hash`. The same workspace and article always yield the same ID, so re-ingestion stays idempotent per workspace.
- **Existing rows.** Keep their legacy IDs and do not rewrite them. Run records carry `canonical_event_ids` (`public_run.py:302`), and `public_signals.event_id` and `artifacts.source_event_id` reference `canonical_events(event_id)` (`schema.sql:41, 67`).
- **Transition.** When workspace A re-ingests an article it already holds under a legacy ID, it gets a second row. Duplicate observations then exist until a read-side dedupe on `(workspace_id, payload.signal_id)` is in place. Read-side dedupe is preferable to rewriting history.
- **Rollback.** Medium. Reverting the derivation leaves new-format rows in place, and the next ingest produces a legacy-format duplicate.
- **Existing pins that break.** `tests/integration/test_public_signal_event_mapping.py:15` compares the full event dict, including the literal `event_id`. `tests/fixtures/public_signals/canonical_events.expected.jsonl` contains the literal `event:public-signal-51ecb279a1f7eb535e24`. Both must be updated in the same change. The docs and comments that describe "the exact shape of `public_signal_event()`" also need updating: `backend/mvp_commerce/supplier_evidence.py:267`, `backend/mvp_commerce/opportunity_scoring.py:571`, `docs/CJ_PUBLIC_SUPPLIER_EVIDENCE.md:190`.
- **Existing pins that survive.** `tests/contracts/test_public_signal_models.py:16-19` (unchanged if `signal_identifier` is unchanged). `tests/integration/test_ingest_public_signals_script.py` (counts only). `tests/system/test_public_signal_replay_certification.py` (equality within a single run). The `canonical_event_ids` assertions in `tests/integration/test_commerce_mvp_shopify_enrichment.py:24` and `tests/system/test_commerce_mvp_vertical_slice.py:8` check counts only.
- **Trade-off.** A workspace-scoped `event_id` forbids sharing one canonical event across tenants. Option (c) does not.

### (b) Keep the IDs; insert-only writes that refuse conflicts and report the drop

- **Supabase.** Use `insert` instead of `upsert`. On a primary-key violation, read the stored `workspace_id`. Same workspace: idempotent. Different workspace: refuse with a `SupabaseEventRepositoryError` subclass. Detect the conflict from the database error, not from a check-then-insert, to avoid a race. `_known_ids` maps `event_id` to `workspace_id`.
- **JSONL.** A cross-workspace collision returns a refusal that is not `idempotent`.
- **Reporting.** `append_public_signal_events` and the run and route responses report only appended IDs and surface refusals.
- **Replay and determinism.** No ID change, so replay hashes and golden fixtures are unchanged, and rollback is trivial. Determinism is weaker: the outcome for workspace B depends on whether workspace A ingested the article first, so the same input gives different results depending on history.
- **Data consequences.** Workspace B never records the observation, so B's replay does not contain it. Any B artifact that cites the event ID points at A's row. A refusal must not name the other workspace, because that would disclose that another workspace holds the event.
- **Existing pins.** `tests/contracts/test_supabase_event_adapter_contract.py:42-48` uses a fake whose `FakeQuery` models only `upsert`, and it asserts same-instance idempotence. The fake needs an `insert` path.
- **Assessment.** A stopgap that makes the loss loud. It does not make the second workspace's record exist.

### (c) Composite key `(workspace_id, event_id)`

- **Supabase.** Primary key `(workspace_id, event_id)`. Composite foreign keys from `public_signals` and `artifacts`, which already carry `workspace_id` (`schema.sql:40, 63`).
- **JSONL.** Dedupe key `(workspace_id, event_id)`.
- **Readers and protocol.** `EventRepository.get(event_id)` becomes ambiguous and must take `workspace_id`. Every adapter and reader changes, including `api/routes/canonical_events.py`.
- **Certification.** `validate_event_sequence` (`replay_certification.py:21`) keys duplicates on `event_id` alone and must key them on `(workspace_id, event_id)`.
- **Replay and determinism.** `event_id` strings are unchanged, so golden fixtures and existing replay hashes are unchanged, and no IDs migrate. Determinism is clean: the outcome depends only on `(workspace, input)`.
- **Blockers in the current schema.** `workspace_id` is nullable (`schema.sql:16`), and `Event.from_workflow_record` sets it to `None` (`backend/contracts/events.py:88`). A composite primary key needs non-null values, so legacy rows need a sentinel or a partial unique index. The existing `on delete set null` clauses (`schema.sql:41, 67`) need redesign for composite keys.
- **Existing pins.** The `event_id` literals in `test_public_signal_event_mapping.py` and the golden fixture stay valid. The Supabase fake, the duplicate-detection tests, and `tests/contracts/test_event_repository_contract.py` and `tests/integration/test_event_repository_adapters.py` need review. Those last two pass on `main` but were not read line by line for this note.
- **Assessment.** The largest blast radius, and a primary-key change is hard to roll back.

## Comparison

| | (a) workspace in ID | (b) refuse conflicts | (c) composite key |
|---|---|---|---|
| Second workspace's observation is recorded | yes | no (refused) | yes |
| Outcome independent of other workspaces' history | yes | **no** | yes |
| Existing event ID strings | unchanged | unchanged | unchanged |
| Replay hash of new rows | changes | unchanged | unchanged |
| Golden fixture update | yes | no | no |
| Schema change | none | none | primary key, foreign keys, NOT NULL |
| Reader or protocol change | none | small | large (`get` signature) |
| Transition duplicates | yes, until read-side dedupe | no | no |
| One canonical event shared across tenants | no | no | yes |
| Rollback | medium | easy | hard |

## Recommendation (for review, not decided)

Choose **(a)**, conditional on Q1 below.

- `deploy/supabase/schema.sql:12-13` states that `event_id` is the cross-store replay identity. (a) keeps that single-key contract. (c) changes it.
- (a) is the smallest change to readers, the protocol and the schema.
- Separation holds by construction, with no order dependence.
- Accept transition duplicates and handle them with a read-side dedupe on `(workspace_id, payload.signal_id)`. Do not rewrite historical rows.

Choose **(c)** instead if sharing one canonical event across tenants is a plausible requirement. Do not ship **(b)** except as a temporary guard.

Independently of the option chosen, the reporting defects need fixing: report only appended IDs, derive `write_targets` from actual writes, and surface refusals. That change does not alter identity, but it changes what `written_event_ids` and `write_targets` mean, so it needs its own review.

Proposed sequence: (1) this PR, the note and red tests; (2) decision; (3) identity change with read-side dedupe and golden regeneration; (4) reporting fix.

## Questions for review

- **Q1.** Must existing `public_signal_observed` rows keep their replay hashes in a shared store (Supabase staging) or in committed JSONL? If yes, (a) needs only the read-side dedupe. If staging data is disposable, a backfill is possible, but I do not recommend rewriting history.
- **Q2.** Is the single server-wide JSONL path (`MARKETOS_EVENT_WRITE_JSONL_PATH`) meant to hold several workspaces? If not, that is a separate configuration bug. If so, the collision is reachable in normal use.
- **Q3.** Should one canonical event ever be shared across tenants? A yes favours (c).
- **Q4.** Has PostgREST `merge-duplicates` behaviour been confirmed on the target Supabase version? The reproduction uses a fake that models it. It has not been run against a live database.

## Tests in this PR

Five tests fail on `main`. Each asserts an invariant that (a), (b) and (c) all satisfy, so none of them pre-selects an option.

| Test | Invariant | Why it fails on `main` |
|---|---|---|
| `test_supabase_second_workspace_does_not_reassign_first_workspace_row` | alpha's stored row still belongs to alpha | upsert replaces it (`supabase.py:77`) |
| `test_supabase_same_adapter_never_reports_other_workspace_write_as_idempotent` | beta's write is never an idempotent replay | `_known_ids` keyed by `event_id` (`supabase.py:73-74`) |
| `test_jsonl_second_workspace_write_is_not_reported_as_idempotent_duplicate` | same invariant, JSONL | `repository.py:25-28` |
| `test_reported_event_ids_equal_rows_persisted_for_each_workspace` | reported IDs equal stored IDs, per workspace | `public_sources.py:153-155` |
| `test_cli_second_workspace_written_event_ids_match_rows_stored_for_it` | CLI response equals the file | `scripts/ingest_public_signals.py:64` |

A refusal counts as passing the first two tests when it is raised as `SupabaseEventRepositoryError`, or returned as a non-idempotent `AppendResult`.

All tests use synthetic workspace IDs (`synthetic-workspace-alpha`, `synthetic-workspace-beta`) and the synthetic fixture `tests/fixtures/public_signals/rss_sample.xml`.

**Result on this branch:** 5 failed, 25 passed. The 25 are the existing public-signal and event-adapter tests, all green on `main`.

The Supabase fake models only the current primary key and `upsert`. Options (b) and (c) require updating it to match the chosen implementation.

Not covered here: the run-level `write_targets` claim. Its assertion depends on how a run result reports refusals, and that is part of the decision.

## Out of scope

- No change to `signal_identifier`, `public_signal_event`, the schema, the adapters or any reporting code.
- No migration and no change to persisted rows.
