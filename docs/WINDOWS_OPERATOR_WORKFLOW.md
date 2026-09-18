# Windows operator workflow

Usable Product Validation / Unit Economics path for a Windows PowerShell operator.
This is a **command surface**, not a second scoring engine or storefront.

Sibling owners (do not edit those PRs from this lane):

| PR | Owner | Role |
|----|-------|------|
| #228 | `scripts/operators/run_first_phase_intelligence.ps1` | First-phase intelligence runner |
| #230 | `frontend/src/features/first-phase-cockpit/` | Evidence cockpit UI |
| #238 | `scripts/run_commerce_operations_cycle.py` batch I/O | Commerce-operations batch CLI |

## Exact PowerShell commands

Run from the repository root. Paths with spaces stay quoted.

```powershell
Set-Location -LiteralPath 'C:\Users\HP\Documents\MarketOS'

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 -Command preflight

$out = Join-Path $env:TEMP 'marketos-operator-safe'
New-Item -ItemType Directory -Force -LiteralPath $out | Out-Null

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command fixture-import `
  -Source '.\tests\fixtures\windows_operator\scenarios\hydroponics.json' `
  -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command supplier-import `
  -Source '.\tests\fixtures\supplier_feasibility\cj_manual_import.csv' `
  -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command product-validation -ClientName 'Internal demo' -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command commerce-cycle -Fixture '.\tests\fixtures\commerce_mvp\public_signals.json' -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command batch-manifest -Manifest '.\tests\fixtures\windows_operator\batch_manifest.json'

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command client-safe-export `
  -Source '.\tests\fixtures\windows_operator\scenarios\hydroponics.json' `
  -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command phase-readiness -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command inspect-evidence -Path '.\tests\fixtures\windows_operator\scenarios\hydroponics.json'

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 `
  -Command replay -Packet '.\tests\fixtures\windows_operator\scenarios\hydroponics.json'

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 -Command start-local

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-StagingAcceptance.ps1

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\run_dry_run_scenario_pack.ps1 -OutputDirectory $out

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-MarketOSOperator.ps1 -Command coderos-probe
```

Equivalent Python (Linux CI / disposable worktree):

```powershell
python scripts/operators/windows_operator_workflow.py preflight --json
python scripts/operators/windows_operator_workflow.py scenario-pack --json
```

## Evidence classes

| Class | Meaning |
|-------|---------|
| `fixture` | Deterministic repo fixture / demo |
| `simulated` | Manual import copied through the operator; not live proof |
| `unavailable` | CLI/dependency missing (for example scipy on a thin agent) |
| `not_run` | Intentionally skipped (network, process start, operations-cycle CLI) |
| `blocked` | Live flag, secret-shaped payload, or forbidden path |
| `actual` | **Never emitted** by this workflow |

## What this workflow will not do

- Start API/frontend processes (`start-local` prints commands only)
- Call `--allow-network` / providers / models
- Write into `artifacts/`, `.git`, `.env`, `credentials`, `secrets`, `node_modules`
- Grant launch, ads, orders, payments, publishing, or messaging authority
- Re-rank candidates (cockpit / backend ranking remains server-side)

## Local API / frontend (manual)

Printed by `start-local`, not executed:

```text
python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev
```

Cockpit (when PR #230 is merged): `http://127.0.0.1:5173/operator/first-phase`
Operator events: `/operator/events`

## Rollback

Delete the operator output directory. Revert this PR. No schema migrations.
Do not delete `artifacts/` from this workflow (writes there are rejected).
