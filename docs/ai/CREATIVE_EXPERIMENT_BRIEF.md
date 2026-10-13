# Creative experiment brief

Schema: `MarketOS.CreativeExperimentBrief.v1`

Planning output for one product candidate. It is not an ad, a campaign, or a publishing integration.

## Authorities reused

| Authority | Role |
| --- | --- |
| `evaluation.commerce.opportunity_synthesis` | Candidate id and `decision_thresholds` are copied. Scores are not recomputed. |
| `evaluation.commerce.consumer_attention` | Geography, language, observed pain/hook/objection text, and the candidate `freshness_statuses` set. Attention is not supplier proof or launch authority. |
| `evaluation.commerce.launch_draft_pack.build_launch_draft_pack` | Creative-test rows are consulted. A row is linked only when its hook already appears in observed, market-matching attention evidence. |
| `evaluation.commerce.experiment_draft` | Unchanged. This brief does not import it and cannot publish a campaign or execute spend. |
| TrustOS client export | Not called. This command prints an operator planning record only. |

## Outcomes

`draft_brief` requires a real candidate id, observed attention on the requested geography and language, a customer problem, and at least one message hypothesis. Each of those strings points at an attention evidence field. When the attention candidate includes `freshness_statuses`, that set must be only `fresh`. The report stores a set, not a per-record index, so `stale`, `future_dated`, `unavailable`, or a mixed set is not attributed to one row and does not become a draft.

`insufficient_evidence` is the safe result when the candidate is missing, attention is missing, observations conflict, freshness is not exclusively fresh, the region or language does not match, market labels are absent, or the only offered lines are unsupported claims.

CPA, CTR, budget, lift, and scale thresholds stay `label: assumption`. Missing numbers stay `unevaluated`. Lift is never invented. `financial_fact` stays false.

## Authority

`read_only`, `draft_only`, and `planning_only` stay true. Spend, targeting activation, publishing, account access, customer messaging, orders, payments, provider calls, and client export stay false.

## Commands

```
python -m pytest -q tests/test_creative_experiment_brief.py
python scripts/run_creative_experiment_brief.py --synthesis report.json --attention attention.json --geography MX --language es
```

## Rollback

Delete this note, `evaluation/commerce/creative_experiment_brief.py`, `scripts/run_creative_experiment_brief.py`, and `tests/test_creative_experiment_brief.py`. Do not merge.
