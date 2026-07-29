# Shadow-flag validation status

Seven `_LIVE` env flags in the decision/learning/risk stack run in
shadow mode: both the legacy and new-path value are always computed and
journaled to `event_store` (`state/workflow_executions.jsonl`) every
cycle, but only the legacy path is actually used until a flag flips.

`backend/validation/shadow_flag_report.py` reads that journal back and
reports, per flag: sample count, mean legacy-vs-shadow delta, a
significance test, and a recommendation (`recommend_flip` /
`do_not_flip` / `insufficient_signal` / `insufficient_data`; boolean and
capital-allocation flags report differently — see the module docstring).
It makes no decisions itself — it's read-only reporting for a human (or
a future automated gate) to act on.

Run it any time with:

```python
from backend.validation.shadow_flag_report import generate_report
import json
print(json.dumps(generate_report(), indent=2))
```

## Current status (2026-07-29)

No cycle history exists yet in this environment
(`state/workflow_executions.jsonl` has never been populated by a running
orchestrator here) — every flag reports `insufficient_data` with
`sample_count: 0`. **No flags have been flipped.** This is the correct,
conservative outcome: the harness requires real accumulated evidence
(≥30 samples by default) before recommending anything, and none exists
yet in this environment.

| Flag | Event type | Status |
|---|---|---|
| `SCORING_NORMALIZE_LIVE` | `shadow_decision_scoring` | insufficient_data |
| `PRODUCT_BANDIT_LIVE` | `shadow_product_bandit_weighting` | insufficient_data |
| `REGIME_CONFIDENCE_WEIGHTING_LIVE` | `shadow_regime_confidence_weighting` | insufficient_data |
| `CALIBRATION_HOLDOUT_LIVE` | `shadow_calibration_stats` | insufficient_data |
| `RISK_ADAPTIVE_LIVE` | `shadow_adaptive_risk` | insufficient_data |
| `ORGANIC_GATE_LIVE` | `shadow_organic_gate` | insufficient_data |
| `CAPITAL_POLICY_LIVE` | `shadow_capital_policy` | insufficient_data (always requires human review — see below) |

## Next step

Once the orchestrator has run for long enough to accumulate ≥30 journaled
events per flag (in a real deployment or a long-running staging/simulation
pass), re-run `generate_report()` and act on whichever flags clear
`recommend_flip` with a comfortable margin. `CAPITAL_POLICY_LIVE`'s
report is descriptive-only (mean reallocation magnitude as a fraction of
total budget) since its shadow event carries a whole allocation vector
with no per-event reward signal to test significance against — that one
always needs a human to weigh reallocation magnitude against realized
portfolio performance directly, not an automated recommendation.
