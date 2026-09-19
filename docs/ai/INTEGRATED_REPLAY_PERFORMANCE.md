# Integrated commercial replay performance verification

Lane: `REAL-WORKTREE-REPLAY-CONFORMANCE-AND-RESTORATION-V2`
PR: `#274` `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-arbitration-v2`
Status: draft, do not merge

## Verdict

| Question | Finding |
| --- | --- |
| Which path is canonical? | **#279** — five fixture builders, `run_dry_run_lifecycle`, `lifecycle_events`, `Event.replay_hash`, `replay_summary`. |
| Did this session measure real Event-path replay? | **Yes**, executed in a real exclusive git worktree against the canonical Event path (`MarketOS.worktrees/marketos-pr274-replay-conformance`). |
| Production `Event.replay_hash` changed? | **No.** |
| Production optimization applied? | **No.** Hashes already stable; #280 owns the laboratory. |
| Isolated field-hash identity? | **Rejected** (negative control). |
| Were published #280 numbers re-run? | **No.** |

## Source tree used

- Repository: `ChristianV997/MarketOS`
- Canonical checkout: `c:\Users\HP\Documents\MarketOS` (untouched, preserved)
- Exclusive git worktree: `C:/Users/HP/Documents/MarketOS.worktrees/marketos-pr274-replay-conformance` on branch `grok/marketos-integrated-replay-performance-v1`
- Base / Merge base: `origin/main` (`e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6`)
- Restored #274 module lineage: complete file restored from `020093317047d7b23228d98c0203c23172e03a74` with full Event-path arbitration and timing metrics (`p50`, `p95`, `p99`, `aggregate_replay_hash`). Remote HEAD `01a10738` and earlier `2811061d` truncation resolved.
- Observed heads: #274 `01a10738`, #279 `9f9283a`, #280 `4565cca`, main `e6a2e88e`.
- Antigravity / Ruff / Compileall / Pytest: executed locally in real worktree; zero live attestation; zero authority violations.

## Five-scenario Event-path measurements

Repeats = 5 on this host. Evidence class = `actual_canonical_dry_run` (dry-run builders, no providers). #280 published walls are listed only as unread-only context and were **not** re-executed.

| Scenario | Stage | Evidence | Events | wall ms | p50 | p95 | p99 | Aggregate `Event.replay_hash` |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| hydroponics_positive_candidate | scale_candidate | observed | 17 | 6.942 | 5.815 | 11.730 | 12.464 | `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043` |
| smart_pet_support_burden_candidate | supplier_validated | observed | 17 | 3.093 | 3.142 | 3.461 | 3.469 | `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac` |
| solar_4g_security_blocked_candidate | economics_screened | fixture | 17 | 5.111 | 4.737 | 8.314 | 8.819 | `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9` |
| commodity_electronics_rejected_candidate | supplier_terms_pending | observed | 17 | 2.877 | 2.736 | 3.294 | 3.364 | `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4` |
| high_ticket_deferred_candidate | supplier_validated | observed | 17 | 3.118 | 2.804 | 4.080 | 4.167 | `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe` |

Invariants on every scenario: event IDs and `Event.replay_hash` sequences identical across repeats; aggregate hash stable; sequence issues empty; live authority violations empty; `live_actions_taken=False`; `live_attestation=False`; solar evidence stayed `fixture` (no live upgrade).

RSS after the five-scenario pass: process `VmRSS` (null on Windows).

## Why no production optimization

Same canonical inputs already produce identical `Event.replay_hash` sequences. Changing `Event.replay_hash` or sharing metadata inside `Event.__post_init__` would change identity. #280 already owns the certification `json.dumps` skip. This lane stays a conformance / timing authority.

## Checks

- `python -m compileall` on exclusive files: ok
- `python -m pytest -q tests/test_integrated_replay_perf.py`: 6 passed
- `python -m ruff check evaluation/perf/integrated_replay.py tests/test_integrated_replay_perf.py`: ok (All checks passed)
- `git diff --check`: clean
- Focused #279 stage/event-count contract reproduced here (17 events, expected stages)
- Full `tests/system/test_commercial_dry_run_replay_integration.py`: preserved in main / #279

Do not merge.
