# Experiment draft contract

Lane: `grok/marketos-experiment-draft-contract-v1`  
Schema: `MarketOS.ExperimentDraft.v1`  
Posture: planning and simulation only. No ads, spend, orders, messages, storefront writes, or provider calls.

## Existing authorities reused

| Authority | Role here |
| --- | --- |
| `evaluation.companyos.resource_execution_governor` | Owns caps. This lane only compares `budget_cap` to a supplied `governor_budget_cap`. Action referenced: `launch_ad_experiment`. Never executed. |
| `evaluation.companyos.approval_ledger` | Owns human approval. This lane stores `approval_state` + `approval_request_id`. Request type referenced: `provider_call`. |
| `evaluation.commerce.launch_draft_pack` / `site_draft_builder` | IDs only (`creative_draft_ids`, `landing_page_draft_id`). Packs not rewritten. |
| `backend.economics.kernel` via carried `PlanningEconomics` | Planning values copied, not recalculated. Currency isolated. |
| `evaluation.experiments` | Unchanged observation t-test. Not a second draft contract. |
| TrustOS export boundary | Client-safe report drops internals. |

Do not treat this module as a second Governor, ledger, kernel, or experiment-stats engine.

## States

`proposed`, `evidence_incomplete`, `draft_ready`, `human_review`, `approved_for_simulation`, `simulated`, `paused`, `rejected`, `completed`, `unavailable`.

`campaign_published` and `spend_executed` raise `live_state_unavailable`.

## Commands

```
python -m pytest -q tests/test_experiment_draft.py
python scripts/run_experiment_draft.py --json
python -m compileall evaluation/commerce/experiment_draft.py evaluation/commerce/experiment_draft_scenarios.py scripts/run_experiment_draft.py tests/test_experiment_draft.py
```

## Public sources (not vendored)

| Source | License | Taken |
| --- | --- | --- |
| OpenFeature evaluation details (reason, variant, default) | Apache-2.0 | draft evaluation returns reason/blockers, never a live flag provider |
| GrowthBook experiment draft + hypothesis + stop | MIT | draft-first experiment record; no assignment SDK |
| OpenLineage run identity | Apache-2.0 | SHA-256 replay hash |
| OpenTelemetry naming | Apache-2.0 | path/span-like field names only |

## Rollback

Delete the exclusive files listed in the PR and close the draft PR. No schema migration. No merge.
