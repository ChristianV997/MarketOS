# Phase 1 Readiness Cockpit

The readiness cockpit is the canonical, read-only answer to “what can MarketOS Phase 1 prove now?” It aggregates existing evaluation, validation-pack, canonical-event, credential-readiness, deployment, and safety signals. It is not another intelligence engine, event spine, provider adapter, or deployment controller.

## Readiness states and score

Every category uses an explicit state: `ready`, `partially_ready`, `blocked`, `not_configured`, `fixture_only`, `live_observed`, `degraded`, or `unknown`. The deterministic score is a transparent average of supplier, competition, opportunity, research, commerce, evaluation, events, credentials, validation pack, deployment, and safety states. `score_contributions` exposes each category’s state value, equal weight, and exact points, so the overall number is reproducible and reviewable. It is an operator prioritization aid—not evidence of demand, profit, launch approval, or mutation authority.

| State | Score value | Meaning |
| --- | ---: | --- |
| `ready` / `live_observed` | 1.00 | Structural gate is ready or sanitized live evidence was observed. |
| `partially_ready` | 0.65 | Useful evidence exists with meaningful gaps. |
| `fixture_only` | 0.40 | Code/fixture evidence exists, but no live proof. |
| `degraded` | 0.30 | A run occurred but yielded incomplete/failed evidence. |
| `not_configured` / `unknown` | 0.15 | Operator input or a report is absent. |
| `blocked` | 0.00 | An explicit policy or provider gate prevents progress. |

`live_observed` requires an observed sanitized result. Adapter code or fixture coverage alone is always `fixture_only`.

## Offline command

```powershell
python scripts/phase1_readiness_report.py --json
python scripts/phase1_readiness_report.py --markdown
```

Neither command calls a provider, requires credentials, or writes a report by default. Optional sanitized inputs are explicit:

```powershell
python scripts/phase1_readiness_report.py `
  --validation-pack-report artifacts/phase1_cj_readonly_validation/latest/validation_pack_report.json `
  --evaluation-report artifacts/phase1_cj_readonly_validation/latest/evaluation_report.json `
  --output artifacts/phase1_readiness/latest `
  --markdown
```

Generated output is operational evidence and must remain uncommitted. The loader redacts secret-like keys and token-looking values; it does not retain raw provider payloads.

## Read-only API and operator UI

`GET /api/phase1/readiness` returns the same JSON-safe model. Artifact locations can be supplied only through server-side variables beneath `artifacts/`:

- `MARKETOS_PHASE1_VALIDATION_ARTIFACT`
- `MARKETOS_PHASE1_EVALUATION_REPORT`
- `MARKETOS_PHASE1_COMPARISON_REPORT`
- `MARKETOS_PHASE1_VALIDATION_PACK_REPORT`

The browser cannot choose local file paths, send credentials, initiate validation, or trigger a provider call. The existing `/operator/events` screen includes a compact Phase 1 readiness card with the score, supplier/competition state, blocking gates, and deterministic next action.

## Next-action engine

The cockpit returns exactly one action. Examples:

| Condition | Next action |
| --- | --- |
| CJ credentials absent | `set_cj_credentials_and_run_validation_pack` |
| Credentials configured but live gate absent | `enable_readonly_flag_and_run_validation_pack` |
| Validation pack absent | `run_credential_safe_cj_validation_pack` |
| Authenticated supplier proof absent | `run_live_cj_readonly_probe` |
| Supplier proof exists but competition is weak | `expand_js_competitor_benchmark` |
| Read-only evidence gates are satisfied | `deploy_readonly_validation_stack` |

Mutation phases remain forbidden until a separately approved approval ledger exists. The report never changes those gates.

## Agentic use

Run `python scripts/ai/run_local_quality_gate.py --json` before a PR. It now includes a compact readiness summary. `impact_planner.py --readiness-report <sanitized-report>` prioritizes the reported next action. The plan remains local and deterministic when no artifacts exist.

## Limitations

The cockpit does not validate current source truth, authenticate to CJ, launch the validation pack, or infer profitability. A missing artifact is intentionally reported as missing rather than silently treated as a successful run.
