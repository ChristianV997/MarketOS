# Plan: MarketOS Low-Risk Service Pilot v1

- **Plan ID:** `plan-marketos-low-risk-service-pilot-v1`
- **Task:** Supervised offline pilot for `services.unit_economics`
- **Branch:** `cursor/marketos-low-risk-service-pilot-v1`
- **Status:** `active`

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
