# Shadow Feature Evaluation

This is a read-only certification harness for financially material shadow features. It consumes canonical `Event` fixtures or JSONL inputs, evaluates evidence deterministically, and emits a report. It never changes a feature flag, decision, budget, provider state, or external system.

It complements [Replay Certification](REPLAY_CERTIFICATION.md): replay certification proves an event sequence is valid and deterministic; this harness evaluates whether synthetic shadow evidence is sufficient for a future human-reviewed promotion proposal.

## Core matrix

| Feature | Primary metric | Safety gates | Required evidence |
| --- | --- | --- | --- |
| Attribution reconciliation | Deduplicated recognized-revenue accuracy | No inflation or refund omission | Claims, orders, payments, refunds |
| Capital policy | Risk-adjusted contribution | Budget, concentration, drawdown caps | Budget recommendation, risk state, profit projection |
| Normalized scoring | Ranking calibration | Bounded and supported score terms | Legacy/candidate scores and outcome |
| Adaptive risk | Downside exposure reduction | Never loosen cap in worse risk; kill switch | Risk state, cap, recommendation |
| Supplier/geo economics | Landed contribution margin | No negative-margin expansion | Supplier, shipping, margin, reliability inputs |
| Calibration/regime confidence | Out-of-sample calibration | No rising confidence with worse error/leakage | Prediction, outcome, calibration, regime |

## Classification policy

- `PROMOTE` is certification-only. It needs every required event, adequate sample size, a non-regressive primary metric, and no safety blocker. It **does not** flip a flag.
- `KEEP_SHADOW` is the default for incomplete or undersized evidence.
- `REWORK` means a safety, domain, or evidence-quality rule failed.
- `DELETE` means the primary metric regressed after evidence and safety requirements were otherwise met.

Every possible promotion still needs human review, a separate change, and existing live-mode approvals. Fixture evidence is not production validation.

## Audited flag inventory

The implemented core maps to `ATTRIBUTION_RECONCILE_LIVE`, `CAPITAL_POLICY_LIVE`, `SCORING_NORMALIZE_LIVE`, `RISK_ADAPTIVE_LIVE`, `GEO_ECONOMICS_LIVE`, `CALIBRATION_HOLDOUT_LIVE`, and `REGIME_CONFIDENCE_WEIGHTING_LIVE`. Its static policy inventory records owner locations and promotion risks without importing the owners or their flag managers.

`SUPPLIER_RISK_RANKING_LIVE`, `SUPPLIER_FEEDBACK_LIVE`, `PHASE7_AB_TEST_VALIDITY_LIVE`, `PHASE7_FATIGUE_DETECTION_LIVE`, `PHASE7_URGENCY_SCORING_LIVE`, `PHASE7_MONTE_CARLO_LIVE`, `PHASE8_ORGANIC_CHANNEL_LIVE`, and `PHASE8_AFFILIATE_SCALING_LIVE` are explicitly catalogued as deferred. The harness does not pretend their event evidence is ready; each needs its own canonical fixture vocabulary, blocker cases, and reviewed matrix before it can be evaluated.

The existing `backend.validation.shadow_flag_report` and `backend.validation.shadow_validator` remain legacy read-only reporters. This foundation complements rather than replaces them, and is intentionally restricted to canonical events.

## Fixtures and reports

Committed fixtures in `tests/fixtures/shadow_evaluation/` are synthetic, dry-run canonical events. They cover two attribution, two capital, two scoring, two adaptive-risk, two supplier/geo, and two calibration/regime cases. Expected files assert the intended conservative classifications.

Reports include replay hashes, evidence IDs, requirements, blockers, rationale, and a statement that they have no authority to change live behavior.

The one synthetic `PROMOTE` fixture proves policy behavior only: it establishes that a fully specified record can pass all mechanical certification gates. It is never evidence that the corresponding real feature is ready to promote.

### Fixture vocabulary

A fixture uses a canonical `shadow_feature_observation` event with a core `feature_id`, stable workspace/correlation identifiers, a synthetic/dry-run marker, and an evidence snapshot. The snapshot records `sample_size`, `observed_event_types`, a baseline/candidate primary metric, and named safety metrics. Domain evidence is explicit rather than inferred: attribution gives ground-truth and reconciled revenue, capital gives caps and allocation state, scoring gives dominant-term share, risk gives cap and context, supplier/geo gives landed contribution, and calibration gives confidence/error deltas.

`observed_event_types` is a compact fixture representation, not permission to omit future canonical events. When a legacy writer is migrated, its emitted stream must provide the underlying event vocabulary represented by the fixture. This lets the current foundation certify semantics while avoiding a risky production-writer migration.

### Determinism and scope

The report timestamp is the latest input event timestamp. Feature ordering is by fixture name then feature ID; metric and blocker ordering are stable; JSON keys are sorted. A report contains only declared event payload data, stable canonical replay hashes, and derived calculations. It does not read environment feature flags, perform network I/O, inspect credentials, or import integrations.

The harness has no authority boundary bypass: a canonical event with a `live_authority` payload is a blocker, and advisory-live-authority violations from replay certification are blockers. Its CLI returns successful process status for `REWORK`, `DELETE`, and `KEEP_SHADOW`, because those are valid audit outcomes rather than tool failures.

## CLI

```powershell
python scripts/shadow_feature_evaluation.py --fixtures --json
python scripts/shadow_feature_evaluation.py --fixtures --markdown
python scripts/shadow_feature_evaluation.py --fixtures --json --output artifacts/shadow-feature-evaluation.json
python scripts/shadow_feature_evaluation.py --path tests/fixtures/shadow_evaluation/attribution_pass_candidate.jsonl --feature attribution_reconciliation --json
```

The command is read-only unless `--output` is passed. That option writes only the requested report; it never writes state, workflow logs, flags, provider data, or production events.

## Future evidence before any promotion

1. Add canonical, synthetic or approved redacted replay fixtures with stable IDs/timestamps.
2. Demonstrate required event coverage and correlation/workspace fields.
3. Add blocker and regression fixtures for the candidate.
4. Update expected deterministic reports and tests.
5. Keep the feature in shadow mode until a separately reviewed human-approval change meets the existing safety process.

## What this does not do

It does not replace production attribution, capital allocation, scoring, risk, supplier, calibration, or feature-flag logic. It does not migrate writers to `EventRepository`, call providers, launch ads, spend money, create orders, or mutate commerce systems. See [Event Repository](EVENT_REPOSITORY.md) for the migration sequence.

## Review boundary

This foundation is intentionally a scientific/audit tool, not a deployment gate. A reviewer can use a report to identify missing instrumentation, unsafe candidate behavior, or a bounded set of evidence worth collecting. A reviewer cannot use it as authority to switch a runtime mode.

The first safe migration after this work is new-only canonical event emission behind `EventRepository`, with each migrated writer checked against the fixture vocabulary. Replacing legacy reader or writer behavior, changing a dry-run default, or promoting a shadow flag remains outside this scope.
