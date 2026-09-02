# Windows First-Phase Intelligence Operator

PowerShell entry point: `scripts/operators/run_first_phase_intelligence.ps1`

## Contract

- Fixture-first offline planning only; not live-validated or authoritative.
- Eight bounded stages composed from existing MarketOS CLIs.
- No network, credentials, providers, models, or external mutation by default.
- Writes only when `-OutputDirectory` points to a safe non-forbidden path.
- Emits one deterministic JSON summary on stdout with per-stage evidence classes:
  `actual`, `failed`, `not_run`, `blocked`, `unavailable`.
- Governor and TrustOS stages delegate to their existing offline CLIs; this wrapper does not recreate those authorities.
- Commerce stage uses `run_commerce_mvp_slice.py` on `main`. PR #225 `run_commerce_operations_cycle.py` remains a separate public contract and is `not_run` here.

## Example

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/run_first_phase_intelligence.ps1 -MaxCandidates 3
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/operators/run_first_phase_intelligence.ps1 -OutputDirectory C:\temp\phase1-safe-out -MaxCandidates 2
```
