# Plan: MarketOS Low-Risk Service Pilot v1

- **Plan ID:** `plan-marketos-low-risk-service-pilot-v1`
- **Task:** Supervised offline pilot for `services.unit_economics`
- **Branch:** `cursor/marketos-low-risk-service-pilot-v1`
- **Status:** `active`

## Lane

human_operator

## Objective

Harden the unit economics service boundary for offline, deterministic,
human-supervised planning sessions without adding orchestration or execution
authority.

## Scope

```json
{
  "in_scope": [
    "services/unit_economics/*",
    "tests/services/test_unit_economics/*",
    "docs/plans/active/plan-marketos-low-risk-service-pilot-v1.md"
  ],
  "out_of_scope": [
    "event spine",
    "workspace isolation core",
    "scripts/ai quality gate internals",
    "frontend",
    "provider integrations",
    "CoderOS imports",
    "orchestrators and approval ledgers"
  ]
}
```

## Risk

```json
{
  "level": "LOW",
  "mitigation": "Keep the unit economics pilot offline, deterministic, human-supervised, and bounded to the declared service, tests, and documentation paths."
}
```

## Ownership

The human operator owns approval and review. The supervised service-pilot
implementation remains bounded to the declared unit-economics service lane;
existing governance, orchestration, and provider authorities remain canonical.

## Stop Conditions

- Stop if inputs or calculations are invalid, non-finite, negative where prohibited, or otherwise fail closed.
- Stop if the pilot requires provider access, network access, subprocess execution, orchestration, or external mutation.
- Stop if a changed file falls outside the declared target list or if deterministic tests cannot reproduce the result.

## Target Files

- `services/unit_economics/analyzer.py`
- `services/unit_economics/schemas.py`
- `services/unit_economics/OPERATOR_PILOT.md`
- `tests/services/test_unit_economics/test_analyzer.py`
- `tests/services/test_unit_economics/test_low_risk_service_pilot.py`
- `docs/plans/active/plan-marketos-low-risk-service-pilot-v1.md`

## Verification Commands

- `python -m compileall services tests`
- `python -m ruff check services/unit_economics tests/services/test_unit_economics`
- `python -m pytest -q tests/services/test_unit_economics/`
- `python scripts/ai/run_local_quality_gate.py --from-git --json`
- `git diff --check`

## Evidence Checklist

- [x] service-boundary input validation blocks negative/empty/malformed inputs
- [x] deterministic fingerprint helper added
- [x] pilot tests cover valid, empty, malformed, boundary, duplicate, ledger-default, and safety cases
- [x] operator documentation added under service directory
