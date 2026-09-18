# Integrated commercial replay performance arbitration

Lane: `REPLAY-PERFORMANCE-CANONICAL-CONFORMANCE-V2`
PR: `#274` `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-arbitration-v2`
Status: draft, do not merge

## Verdict

| Question | Finding |
| --- | --- |
| Which path is canonical? | **#279** — five fixture builders, `run_dry_run_lifecycle`, `lifecycle_events`, `Event.replay_hash`, `replay_summary`. |
| Does #274 measure real commercial replay? | Only when those imports succeed. This sandbox classifies them **unavailable**. |
| Does #280 duplicate #274 scope? | **#280 owns the laboratory**. #274 does not copy those files. |
| Did any optimization change `Event.replay_hash`? | **No.** Field-hash is a negative control. |
| Isolated 3.6x survive imports? | **No.** |

## Conformance execution (this session)

- `git clone` MarketOS: **failed** (no credentials)
- Combined #274/#279 worktree: **unavailable**
- CoderOS / grok inspect: **unavailable**
- Antigravity: **not invoked**
- Evidence classification here: **unavailable**
- Production optimization: **not applied**

Read-only #280 published fixture numbers (not re-run):

- cycle mean 16.15 ms, p50 15.51 ms, p95/p99 23.86 ms
- five-scenario walls 7.30 / 2.53 / 2.25 / 4.72 / 4.27 ms
- zero hash drift

Observed heads: #279 `07a28201`, #280 `c5fcc01f`, main `e6a2e88e`.

Do not merge.
