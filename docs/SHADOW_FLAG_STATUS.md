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

## Current status (2026-07-29, updated)

No production deployment has run in this environment yet, so this
section is based on a **200-cycle dry-run simulation** (`SystemState` +
`backend.execution.loop.run_cycle`, the same synchronous path
`.github/workflows/ci.yml`'s smoke-test job exercises), journaled to a
dedicated event store (not the shared `state/workflow_executions.jsonl`,
which accumulates incidental noise from running the test suite and must
not be used for flip decisions — see caveat below). **This is simulation
evidence, not production telemetry — no flags have been flipped**, and
none should be based on this alone; it exists to (a) prove the harness
works end-to-end for the first time in this environment and (b) surface
an early, honest read on each flag's behavior.

| Flag | Event type | Samples | Recommendation |
|---|---|---|---|
| `SCORING_NORMALIZE_LIVE` | `shadow_decision_scoring` | 1000 | `do_not_flip` — shadow score differs from legacy by a significant, non-trivial margin (mean Δ ≈ -6.4) |
| `PRODUCT_BANDIT_LIVE` | `shadow_product_bandit_weighting` | 1000 | `insufficient_signal` — legacy and shadow paths are identical in this simulation (mean Δ = 0), so there's nothing yet to distinguish |
| `REGIME_CONFIDENCE_WEIGHTING_LIVE` | `shadow_regime_confidence_weighting` | 1000 | `do_not_flip` — significant divergence from legacy (mean Δ ≈ -1.4) |
| `CALIBRATION_HOLDOUT_LIVE` | `shadow_calibration_stats` | 201 | `insufficient_signal` — mixed: bias magnitude shows no significant difference, but holdout uncertainty is significantly higher than legacy; the two sub-metrics disagree, so the harness correctly declines to recommend a flip |
| `RISK_ADAPTIVE_LIVE` | `shadow_adaptive_risk` | 0 | `insufficient_data` — see caveat below: this flag's shadow journaling is wired into `backend/risk/gate.py`'s live-spend check path, which a dry-run simulation never exercises |
| `ORGANIC_GATE_LIVE` | `shadow_organic_gate` | 0 | `insufficient_data` — same caveat: only exercised via the commerce/organic-posting path, not the bare execution loop |
| `CAPITAL_POLICY_LIVE` | `shadow_capital_policy` | 200 | `insufficient_signal_requires_human_review` (always descriptive-only — see below) |

**Caveat — two flags structurally can't accumulate data from this kind
of simulation.** `RISK_ADAPTIVE_LIVE` and `ORGANIC_GATE_LIVE` are only
journaled from the money-spend and organic-posting paths respectively
(`backend/risk/gate.py::check_spend`/`enforce`, and
`backend/decision/organic_gate.py`), which the bare execution-loop
simulation above never reaches. Generating real samples for these two
requires either running the commerce/orchestrator loop (dry-run is fine
— the shadow journal doesn't require real spend, just that the code path
executes) for enough cycles to produce campaign-launch and organic-post
activity, or a real deployment. Not attempted in this pass to keep the
simulation's scope matched to what it actually claims to test.

## Next step

Re-run the simulation (or, better, a real staging/production deployment)
for long enough to accumulate ≥30 events for `RISK_ADAPTIVE_LIVE` and
`ORGANIC_GATE_LIVE` specifically (via the commerce/orchestrator loop, not
the bare execution loop), and accumulate real production-grade evidence
for the other five before treating any `do_not_flip`/`insufficient_signal`
result above as final — this pass's purpose was proving the harness
works and getting an early read, not making a production go/no-go call.
`CAPITAL_POLICY_LIVE`'s report stays descriptive-only (mean reallocation
magnitude as a fraction of total budget) since its shadow event carries a
whole allocation vector with no per-event reward signal to test
significance against — that one always needs a human to weigh
reallocation magnitude against realized portfolio performance directly,
not an automated recommendation.

Reproduce this simulation with:

```python
import os
os.environ["STATE_DIR"] = "/tmp/shadow_sim_state"  # set before any backend.* import

from backend.core.state import SystemState
from backend.execution.loop import run_cycle

s = SystemState()
for _ in range(200):
    s = run_cycle(s)

from backend.orchestration.event_store import EventStore
from backend.validation.shadow_flag_report import generate_report
import json
store = EventStore("/tmp/shadow_sim_state/workflow_executions.jsonl")
print(json.dumps(generate_report(store=store), indent=2))
```
