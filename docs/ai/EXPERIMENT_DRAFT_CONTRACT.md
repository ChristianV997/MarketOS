# Experiment draft contract

Lane: `grok/marketos-experiment-draft-contract-v1`
Schema: `MarketOS.ExperimentDraft.v1`
Posture: planning and simulation only. No ads, spend, orders, messages, storefront writes, or provider calls.

## Existing authorities reused

| Authority | Role here |
| --- | --- |
| `evaluation.companyos.resource_execution_governor` | Owns caps. Action referenced: `launch_ad_experiment`. Never executed. |
| `evaluation.companyos.approval_ledger` | Owns approval. Request type referenced: `ad_launch` (blocked_in_current_mode). |
| Launch Draft Pack / Site Draft Builder | IDs only. Packs not rewritten. |
| `backend.economics.kernel` | Planning values copied, not recalculated. Currency isolated. |
| `evaluation.experiments` | Unchanged observation t-test. Not a second draft contract. |
| TrustOS export boundary | Client-safe report drops internals. |

## States

`proposed`, `evidence_incomplete`, `draft_ready`, `human_review`, `approved_for_simulation`, `simulated`, `paused`, `rejected`, `completed`, `unavailable`.

`campaign_published` and `spend_executed` raise `live_state_unavailable`.

## Commands

```
python -m pytest -q tests/test_experiment_draft.py
python scripts/run_experiment_draft.py --json
```

## Public sources (not vendored)

| Source | License | Taken |
| --- | --- | --- |
| OpenFeature evaluation details | Apache-2.0 | reason/blockers, never a live flag provider |
| GrowthBook experiment draft | MIT | hypothesis + stop; no assignment SDK |
| OpenLineage run identity | Apache-2.0 | SHA-256 replay hash |
| OpenTelemetry naming | Apache-2.0 | field names only |

## Rollback

Delete exclusive experiment_draft* files and close the draft PR. No merge.
