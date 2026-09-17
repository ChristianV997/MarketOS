# Windows operator command surface

Companion to `docs/WINDOWS_OPERATOR_WORKFLOW.md`.

## Entry points

| File | Purpose |
|------|---------|
| `Invoke-MarketOSOperator.ps1` | Twelve dry-run commands |
| `run_dry_run_scenario_pack.ps1` | Five-scenario packet |
| `Invoke-StagingAcceptance.ps1` | Staging contract (default not_run) |
| `windows_operator_workflow.py` | Canonical implementation (CI + Windows) |

PR #228 `run_first_phase_intelligence.ps1` is a **different** runner. Do not merge
the scripts. Call #228 when you need the eight-stage intelligence pipeline; call
this surface for sprint-style operator commands and the scenario pack.
