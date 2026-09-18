# Commercial replay + performance integration v2

Lane: `COMMERCIAL-REPLAY-PERFORMANCE-INTEGRATION-V2`
Branch: `grok/marketos-commercial-replay-integration-v2`
Base: `#248` `codex/marketos-profit-evidence-kernel-v1` @ `38b53a264bf9e1343b47161d2647149a5ab3918f`
Selected economics authority: `#248` `backend.economics.kernel` (not `#250`'s copy)
Posture: fixture / dry-run only. No live providers. No merge.

## Ownership resolution

| PR | Classification | This lane |
| --- | --- | --- |
| `#248` | Canonical financial-evidence kernel | consume, do not copy |
| `#250` | Duplicate kernel + unique commerce contracts | kernel rejected; unique contracts salvaged |
| `#255` | Isolated benchmark harness (`evaluation/perf/commerce_engine.py`) | left on `#255`; not a production normalizer |
| `#256` | Unique replay projection + system tests stacked on `#250` | unique files retargeted onto `#248` |
| `#211` | Artifact-store path escape | still owned by `#211` (strict xfail remains) |
| `#230` | Frontend cockpit | not modified |
| `#247` | Research-to-decision packet | not copied |
| `#249` | Deploy harness | not copied |
| `#258` | Deploy readiness | unresolved elsewhere |

`evaluation/perf/commerce_engine.py` is **not** the production offer path.
It is a bounded measurement seam with its own normalize + conflict scan.
Do not import it from `backend.commerce`, `evaluation.commerce`, or
`backend.economics`. Measured `#255` result (sandbox, fixture-only):

- 1500-row pairwise mean: 25.172 ms
- 1500-row indexed mean: 6.222 ms
- output equivalence: true
- live_attestation on fixture: false

That optimization stays inside the isolated harness until a production
owner proves the same bottleneck in the canonical path.

## Exclusive files on this branch

Salvaged from `#250` (not kernel):

- `evaluation/commerce/canonical.py`
- `evaluation/commerce/promotion.py`
- `evaluation/commerce/business_model_economics.py`
- `evaluation/commerce/dry_run_lifecycle.py`
- `evaluation/commerce/dry_run_scenarios.py`
- `evaluation/companyos/service_engagement.py`
- `tests/commerce_canonical/*`

Salvaged from `#256`:

- `evaluation/commerce/dry_run_events.py`
- `tests/system/test_commercial_dry_run_replay_integration.py`

Added here:

- `docs/ai/COMMERCIAL_REPLAY_PERFORMANCE_INTEGRATION.md`
- `scripts/run_commercial_replay_integration.py`
- Mexico hydroponics MXN scenario (same kernel, no FX)

## Commands (operator worktree)

```powershell
git fetch origin --prune
git worktree add --detach C:\Users\HP\Documents\MarketOS.worktrees\commercial-integration-v2 origin/grok/marketos-commercial-replay-integration-v2
Set-Location C:\Users\HP\Documents\MarketOS.worktrees\commercial-integration-v2
python -m pytest -q tests/commerce_canonical tests/system/test_commercial_dry_run_replay_integration.py
python scripts/run_commercial_replay_integration.py --json
```

Windows repository execution from this sandbox: **unavailable**.

## Evidence classes used

actual | simulated | fixture | unavailable | not_run | failed | malformed | blocked | ci_unavailable

CI on current MarketOS PRs remains `ci_unavailable` until an executed
runner is observed. Local dry-run quality-gate output is not merge evidence.

## Rollback

Delete the exclusive files / close the PR. `#248` kernel is untouched.
`#255` and `#256` branches remain as historical sources.
