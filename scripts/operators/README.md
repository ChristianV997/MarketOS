# Windows operator command surfaces

The operator scripts are fixture-first and offline by default. They do not
enable network, credentials, providers, models, or external mutation.

## Sprint command surface

Companion to `docs/WINDOWS_OPERATOR_WORKFLOW.md`.

| File | Purpose |
|------|---------|
| `Invoke-MarketOSOperator.ps1` | Twelve dry-run commands |
| `run_dry_run_scenario_pack.ps1` | Five-scenario packet |
| `Invoke-StagingAcceptance.ps1` | Staging contract (default `not_run`) |
| `windows_operator_workflow.py` | Canonical implementation (CI + Windows) |

## First-phase intelligence runner

PowerShell entry point: `scripts/operators/run_first_phase_intelligence.ps1`

This is a separate eight-stage intelligence pipeline. It emits a deterministic
`MarketOS.FirstPhaseOperatorSummary.v1` summary and a nested
`MarketOS.FirstPhaseExecutionEvidence.v1` packet. Fixture-demo success is
classified as `fixture`; manual-import success is `simulated`; neither is live
`actual` evidence. Live attestation switches remain blocked.

The runner delegates Governor and TrustOS decisions to their existing offline
authorities. Its commerce stage uses `run_commerce_mvp_slice.py`; the
commerce-operations cycle remains a separate public contract.

Call the first-phase runner when the eight-stage intelligence pipeline is
needed, and the sprint command surface for operator scenarios. Do not merge
their entry points or treat either as live execution authority.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/run_first_phase_intelligence.ps1 -MaxCandidates 3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/run_first_phase_intelligence.ps1 -OutputDirectory C:\temp\phase1-safe-out -MaxCandidates 2
```
