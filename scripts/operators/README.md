# Windows First-Phase Intelligence Operator

PowerShell entry point: `scripts/operators/run_first_phase_intelligence.ps1`

## Contract

- Fixture-first offline planning only; not live-validated or authoritative.
- Eight bounded stages composed from existing MarketOS CLIs.
- No network, credentials, providers, models, or external mutation by default.
- Writes only when `-OutputDirectory` points to a safe non-forbidden path.
- Emits one deterministic JSON summary (`MarketOS.FirstPhaseOperatorSummary.v1`) on stdout.
- Nested execution evidence packet (`MarketOS.FirstPhaseExecutionEvidence.v1`) includes run mode, stage status, evidence classes, fixture/manual labels, input fixture identity, provenance, freshness, blocked/unavailable reasons, Governor result, TrustOS result, commerce decision packet, and a deterministic fingerprint.
- Default fixture-demo success is classified as `fixture`, never as live `actual` execution.
- Manual-import success is classified as `simulated`, never as live `actual` execution.
- Live attestation switches (`-ClaimLiveExecution`, `-LiveValidated`) are blocked.
- Governor and TrustOS stages delegate to their existing offline CLIs; this wrapper does not recreate those authorities.
- Commerce stage uses `run_commerce_mvp_slice.py` on `main`. PR #225 `run_commerce_operations_cycle.py` remains a separate public contract (`operations_cycle: not_run` in decision packet).

## Example

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/run_first_phase_intelligence.ps1 -MaxCandidates 3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/run_first_phase_intelligence.ps1 -OutputDirectory C:\temp\phase1-safe-out -MaxCandidates 2
```
