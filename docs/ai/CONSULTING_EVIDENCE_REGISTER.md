# Consulting Evidence Register

## Purpose

`services.consulting_evidence_register` is a deterministic, offline register for persisted consulting component reports. It makes evidence lineage, assumptions, freshness, conflicts, gaps, and human-review requirements visible without becoming a second market, consumer, supplier, economics, engagement, marketing, readiness, or opportunity scorer.

## Ownership and non-overlap

This additive package owns only:

- `services/consulting_evidence_register/**`
- `tests/services/test_consulting_evidence_register/**`
- `tests/fixtures/consulting_evidence_register/**`
- `docs/ai/CONSULTING_EVIDENCE_REGISTER.md`

It does not modify existing authorities or open-PR paths. It does not call providers, create events, persist records, send messages, publish campaigns, place orders, make payments, contact customers, or authorize launch.

## Call graph

```text
build_evidence_register(reports)
  -> _normalize_report
      -> _walk_unsafe (reject nested sensitive and external-action claims)
      -> validate report identity, workspace, status, and capability shapes
  -> sort persisted report references
  -> aggregate fact-level evidence and provenance
  -> preserve partial/unavailable/unknown states, gaps, stale evidence, and conflicts
  -> build client-safe projection
  -> canonical sorted serialization and SHA-256 fingerprint
  -> ConsultingEvidenceRegister
```

## Input contract

Each persisted report supplies `report_id`, `fingerprint`, `workspace_id`, `service_name`, `status`, and a `capabilities` mapping. A capability contains an explicit `state` (`available`, `partial`, `unavailable`, or `unknown`), `facts`, `provenance`, optional `observed_at`, optional `freshness`, optional `missing`, and optional `conflicts`. Reports may also supply `assumptions` and `limitations`.

The register preserves report IDs and fingerprints, and every normalized fact area includes `source_report_id`, `source_fingerprint`, `evidence_state`, and provenance. It does not infer unsupported values or upgrade missing evidence.

## Output semantics

- `status` is `empty`, `partial`, or `complete`; it is not a recommendation or score.
- `readiness` is false unless reports exist, all represented capabilities are available, and no gaps or conflicts remain.
- `gaps` records unavailable, partial, unknown, and explicitly missing capability information.
- `conflicts` records conflict markers without selecting a winner.
- stale evidence remains visible and adds a limitation; it is never silently refreshed or treated as current.
- `assumptions` and `limitations` are retained as review inputs.
- `human_review.required` is always true for this projection.
- `decision_boundary.scoring` and `decision_boundary.authorization` are `not_performed`.
- `safety.external_actions_authorized` and `safety.provider_calls_performed` are always false.

The fingerprint is a SHA-256 digest of canonical sorted JSON over the register's stable content. The caller-supplied `generated_at` is validated as metadata but intentionally excluded from the output identity so equivalent persisted facts remain reproducible.

## Client-safe behavior

The client-safe projection contains only workspace identity, status/readiness, capability states, evidence facts/provenance, gaps, conflicts, human-review requirement, and the explicit external-action denial. Nested sensitive keys and external-action claims fail closed with stable `ConsultingEvidenceInputError`; unsafe content is not silently redacted into an ambiguous result.

This package does not bypass TrustOS. A future integration must pass the resulting projection through the canonical TrustOS workspace/export boundary before any client delivery. The package itself has no workspace registry, database, or network authority.

## Validation and limitations

Focused tests cover complete, partial, unavailable, stale, conflicting, deterministic, client-safe, malformed, nested-sensitive, empty, and external-action inputs. The package is an aggregation boundary, not a freshness calculator, conflict resolver, economics calculator, readiness gate, or launch authorization surface. Human review remains mandatory before client use.

Rollback is isolated: revert the commit or remove the four owned path groups. No existing module imports this new package on this branch.
