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

- **Owner:** human_operator (supervised review and approval gate)
- **Implementer lane:** bounded service-pilot changes only; orchestration and provider authorities remain canonical elsewhere

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

## Interface Contracts

```json
{
  "entrypoints": {
    "run_unit_economics": "tuple[UnitEconomicsResult, CommercialRunEnvelope] — never raises",
    "from_ledger": "tuple[UnitEconomicsResult, CommercialRunEnvelope] — never raises; ledger unavailable degrades to calculator defaults"
  },
  "envelope": {
    "mode": "dry_run",
    "proposed_spend": 0.0,
    "actual_spend": 0.0,
    "status_completed": "valid economics computed offline",
    "status_blocked": "invalid_input rejected before margin math",
    "status_failed": "calculation_failed; must not be reported as completed"
  },
  "result": {
    "verdicts": ["profitable", "breakeven", "loss", "invalid_input", "calculation_failed", "unknown"],
    "fingerprint": "UnitEconomicsResult.deterministic_fingerprint() excludes timestamps and experiment ids"
  },
  "evidence": {
    "ledger_empty": "simulated defaults (monthly_ad_spend=500, expected_monthly_revenue=5000)",
    "ledger_unavailable": "degrades without raising; not live proof"
  }
}
```

## Verification Commands

- `python -m compileall services/unit_economics tests/services/test_unit_economics`
- `python -m ruff check services/unit_economics tests/services/test_unit_economics`
- `python -m pytest -q tests/services/test_unit_economics/ tests/test_ledger/test_service_integration.py`
- `python -m pytest -q tests/test_plan_marketos_low_risk_service_pilot.py`
- `python scripts/ai/run_local_quality_gate.py --from-git --json`
- `git diff --check`

## Acceptance Criteria

- [x] Invalid, empty, boolean, NaN, and infinite inputs are blocked with `verdict=invalid_input` and `envelope.status=blocked`
- [x] Calculator failures return `verdict=calculation_failed` and `envelope.status=failed` (never `completed`)
- [x] Valid inputs complete with `envelope.status=completed`, `dry_run=true`, and zero spend
- [x] Duplicate runs produce identical `deterministic_fingerprint()` values
- [x] `from_ledger` on empty/unavailable ledger degrades to simulated defaults without execution authority
- [x] No provider, network, order, payment, or ad activation paths are introduced
- [x] All verification commands pass on the pilot branch

## Recovery Conditions

- If verification fails: stop, do not expand scope, and repair only within the declared target files.
- If calculator or ledger degradation regresses: restore fail-closed envelope semantics before re-running pilot tests.
- If scope must grow beyond unit economics: close this plan and open a new bounded plan; do not merge pilot changes into unrelated lanes.
- If envelope status incorrectly reports `completed` after a calculation failure: block PR review until `mark_failed` semantics are restored.

## Evidence Checklist

- [x] service-boundary input validation blocks negative/empty/malformed inputs
- [x] deterministic fingerprint helper added
- [x] pilot tests cover valid, empty, malformed, boundary, duplicate, ledger-default, and safety cases
- [x] operator documentation added under service directory
