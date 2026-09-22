# Consulting Portfolio Synthesis Service

## Purpose

`services.consulting_portfolio` builds a deterministic, offline portfolio decision package from persisted component-report facts. It is an aggregation and traceability layer for consulting engagements; it is not a second Product Opportunity Synthesis scorer.

The service accepts report references carrying a stable `report_id`, source `fingerprint`, service name, availability state, observation metadata, and persisted facts. It preserves facts, report IDs, fingerprints, and fact-to-report provenance. It does not fetch reports, call providers, infer confidence, recompute economics, or mutate any external system.

## Input contract

Each component report is a mapping with:

- `report_id`: non-empty stable identifier; duplicate IDs are rejected;
- `fingerprint`: non-empty source fingerprint; missing fingerprints fail closed;
- `service`: source authority name;
- `status`: `available`, `partial`, or `unavailable` (unknown values are treated as unavailable);
- `observed_at`: source observation metadata;
- optional `stale` and `conflicting` flags;
- `facts`: persisted, already-produced values grouped by area.

Supported fact areas include:

- product/service assessments;
- market research;
- demand and consumer attention;
- supplier and logistics findings;
- unit/service economics;
- customer intelligence;
- marketing/publicity strategy;
- creative testing;
- blockers and evidence gaps;
- repeated risks;
- package readiness;
- assumptions;
- recommended sequence;
- next-best actions;
- limitations.

Unknown fact areas are ignored rather than interpreted. This prevents the portfolio layer from silently inventing semantics for an authority it does not own.

## Output contract

`synthesize_portfolio(reports)` returns `PortfolioSynthesis` with:

- stable, canonical JSON serialization via `to_json()`;
- deterministic SHA-256 package fingerprint;
- sorted report IDs, services, facts, blockers, gaps, risks, actions, and sequences;
- `report_fingerprints` and `provenance_by_area` for traceability;
- capability state per service, preserving `partial` and `unavailable`;
- stale/conflicting report lists and fail-closed blockers;
- explicit assumptions and limitations;
- `human_review.required=True` and pending state;
- `decision_boundary` stating that scoring and Opportunity Synthesis were not performed;
- a read-only safety declaration with all external-action capabilities disabled;
- `client_safe_projection`, containing client-appropriate facts and provenance only.

An empty input produces an `unavailable`, `not_ready` package requiring human review. Stale or conflicting evidence prevents readiness. Missing evidence is reported; it is never converted into confidence or a positive decision.

## Safety and boundaries

The service is advisory and read-only. It never authorizes or performs spending, publishing, messaging, orders, payments, supplier actions, or launch. Input claims such as `launch_authorized` or `payment_authorized` are rejected when asserted. Internal prompts, formulas, heuristics, raw provider payloads, credentials, and secret-like fields are not included in the client-safe projection.

The implementation does not import or edit existing report registry, Opportunity Synthesis, economics, replay, compliance, service-delivery, TrustOS-core, deployment, frontend, or readiness authorities. Those authorities remain owners of their respective contracts.

## Call graph

```text
synthesize_portfolio(reports)
  -> _normalize_reports
      -> _reject_external_claims
  -> aggregate persisted facts and provenance
  -> _client_projection
  -> _sha256(_canonical_json(result))
  -> PortfolioSynthesis
```

## Verification

Focused tests use fixture-backed reports for complete, partial/unavailable, stale/conflicting, empty, duplicate/missing-fingerprint, external-action, determinism, provenance, and client-safe projection cases. Tests are offline and do not access suppliers, providers, credentials, networks, orders, payments, publishing, messaging, or databases.
