# Event Migration Pilot Fixtures

This fixture set covers the sole migration pilot: the non-authoritative `shadow_mode_decision` journal in `backend.deployment.shadow_mode`. The legacy JSONL record remains authoritative. Canonical events are a default-off parallel mirror only.

All records are synthetic, dry-run, and stable. The expected canonical event is what `build_shadow_mode_decision_event()` emits from the legacy record. The two small status fixtures document disabled and canonical-failure behavior without writing a real workflow log.
