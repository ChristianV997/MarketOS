# Event Migration Pilot: `shadow_mode_decision`

## Purpose

This is the first narrow writer migration pilot toward the canonical `EventRepository`. It dual-writes the legacy `shadow_mode_decision` record emitted by `backend.deployment.shadow_mode.ShadowModeController.record_shadow_decision`.

The legacy workflow JSONL append remains authoritative. The canonical event is a best-effort, non-authoritative mirror used only for compatibility certification. It does not affect the controller return value, validation status, feature flags, launch decisions, budget, provider access, or external state.

## Why this path

The selected path is a generic Phase 7/8 shadow comparison journal. It already records baseline/new values side by side and its append is contained in a fail-safe `try/except`. It is lower risk than a business ledger or workflow lifecycle writer because consumers use it for audit/validation rather than for an authoritative operational transition.

Deferred candidates:

- `shadow_organic_gate`: close to paid-launch gating, even though its legacy outcome is retained by default.
- `shadow_live_mode_checklist`: close to real mutation eligibility and credential/budget checks.
- capital, attribution, risk, supplier, and geo journals: financially material and covered by the replay/evaluation foundations first.
- workflow JSONL replacement: the existing store remains the lifecycle authority.
- advisory artifact journals: useful later, but lower migration value than proving shadow-decision parity.

## Dual-write behavior

1. The controller performs its existing `event_store.append(...)` exactly as its authoritative legacy write.
2. Only after that append succeeds, it invokes `append_shadow_mode_decision_pilot`.
3. The helper is disabled unless explicitly injected with `canonical_pilot_enabled=True` or `MARKETOS_CANONICAL_EVENT_PILOT=1` is set.
4. A repository must be injected. There is no runtime default JSONL repository and no global repository state.
5. A canonical failure is logged and retained in `last_canonical_pilot_result`; the legacy record and controller result are still returned.

The canonical envelope contains `migration_pilot`, `legacy_path`, `legacy_event_type`, `dual_write`, `dry_run`, and `non_authoritative` metadata. It has no live authority and cannot change feature flags.

## Compatibility report

`backend.events.migration_compatibility` compares the legacy record and canonical event for event type, payload, workspace, aggregate ID/type, causation/correlation IDs, timestamp, source, pilot metadata, replay hash availability, and one-for-one ordering. It validates the legacy input before reporting parity and only recommends another non-live pilot when parity is clean.

Known limitation: this pilot verifies a single homogeneous journal schema. It does not prove that legacy workflow JSONL is globally canonical, provide distributed durability, or replace readers.

## Fixtures and CLI

```powershell
python scripts/event_migration_pilot_report.py --fixtures --json
python scripts/event_migration_pilot_report.py --fixtures --markdown
python scripts/event_migration_pilot_report.py --fixtures --json --output artifacts/event-migration-pilot-report.json
```

The CLI reads fixture paths by default. It accepts `--legacy-path` and `--canonical-path` for explicit synthetic/redacted inputs. It is read-only unless `--output` is passed; that option writes only the report artifact.

## Rollback

Set `MARKETOS_CANONICAL_EVENT_PILOT=0` or remove the injected enablement/repository. The legacy `event_store` append continues unchanged. A full rollback removes the two `backend.events.migration_*` helpers and the single post-append helper call, without requiring data migration.

## Gates before another writer pilot

Another pilot should not be selected merely because its records resemble this event. It needs a single authoritative legacy owner, a defined payload mapping, deterministic fixture inputs, a failure-isolation test, and a consumer impact assessment. A writer closer to commerce, payment, advertising, provider mutation, or workflow lifecycle requires a stronger dedicated parity plan.

The canonical mirror must remain optional and injected during the first phase. A future safe step may provide a local repository factory for a carefully scoped non-live writer, but no default repository is created here because it could silently create a new durable event path outside the reviewed migration plan.

## Operational interpretation

`parity: true` means the expected canonical representation preserved the tested legacy record’s semantics. It does not mean all historical legacy records are valid, that multiple writers have been migrated, or that canonical events are ready to become authoritative. `parity: false` is an engineering blocker, not an invitation to retry automatically: keep the legacy path and correct the mapper or fixture first.

The pilot’s replay hash is derived from the full canonical envelope, including its fixed migration metadata. That makes a changed mapper, omitted context field, or metadata regression visible in the compatibility report even when a legacy consumer would still accept the original JSONL record.

Canonical records are deliberately not fed back into `shadow_flag_report`, `shadow_validator`, or any workflow/event-store reader. Parallel read migration is a separate change after sufficient dual-write evidence has accumulated.

## Not migrated

This does not migrate workflow events, ledger events, attribution, capital policy, scoring, risk, supplier/geo economics, experiment lifecycle, advisory intelligence writers, or replay-store persistence. It does not enable flags or live behavior.
