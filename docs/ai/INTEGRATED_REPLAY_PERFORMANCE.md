# Integrated commercial replay performance verification

Lane: `REPLAY-PERFORMANCE-CANONICAL-VERIFICATION-V3`
PR: `#274` `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-arbitration-v2`
Status: draft, do not merge

## Verdict

| Question | Finding |
| --- | --- |
| Which path is canonical? | **#279** — five fixture builders, `run_dry_run_lifecycle`, `lifecycle_events`, `Event.replay_hash`, `replay_summary`. |
| Did this session measure real Event-path replay? | **Yes**, on a sparse GitHub-blob validation tree. Not a `git worktree` of origin (private clone failed). |
| Production `Event.replay_hash` changed? | **No.** |
| Production optimization applied? | **No.** Hashes already stable; #280 owns the laboratory. |
| Isolated field-hash identity? | **Rejected** (negative control). |
| Were published #280 numbers re-run? | **No.** |

## Source tree used

- Git clone of `ChristianV997/MarketOS`: failed (private, no local credentials).
- Exclusive git worktree: unavailable.
- Combined validation tree: `/tmp/marketos-combined-274-279` (sparse materialization).
- Kernel / Event / certification blobs: main `e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6`.
- Dry-run builders: #279 head `bfe403bbf4688a6eb0f4e008385f179658407a8e`.
- Restored #274 module lineage: complete file at `020093317047d7b23228d98c0203c23172e03a74` (remote HEAD `2811061d` was truncated).
- Observed heads: #279 `bfe403bb`, #280 `67294b54`, main `e6a2e88e`.
- CoderOS / grok inspect / Antigravity / Ruff / session_finish / GitHub CI: unavailable or not invoked.

## Five-scenario Event-path measurements

Repeats = 5 on this host. Evidence class = `actual_canonical_dry_run` (dry-run builders, no providers). #280 published walls are listed only as unread-only context and were **not** re-executed.

| Scenario | Stage | Evidence | Events | wall ms | p50 | p95 | p99 | Aggregate `Event.replay_hash` |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| hydroponics_positive_candidate | scale_candidate | observed | 17 | 0.865 | 0.645 | 1.662 | 1.662 | `6fb533515213…e448043` |
| smart_pet_support_burden_candidate | supplier_validated | observed | 17 | 0.645 | 0.669 | 0.727 | 0.727 | `454324ce4704…2095ac` |
| solar_4g_security_blocked_candidate | economics_screened | fixture | 17 | 0.622 | 0.586 | 0.787 | 0.787 | `44ea844bac5e…38f3e9` |
| commodity_electronics_rejected_candidate | supplier_terms_pending | observed | 17 | 0.575 | 0.547 | 0.644 | 0.644 | `b19c522f0ecc…131aa4` |
| high_ticket_deferred_candidate | supplier_validated | observed | 17 | 0.566 | 0.567 | 0.603 | 0.603 | `f9d709c9366b…7c13fe` |

Invariants on every scenario: event IDs and `Event.replay_hash` sequences identical across repeats; aggregate hash stable; sequence issues empty; live authority violations empty; `live_actions_taken=False`; `live_attestation=False`; solar evidence stayed `fixture` (no live upgrade).

RSS after the five-scenario pass: ~19 MiB process `VmRSS`.

## Why no production optimization

Same canonical inputs already produce identical `Event.replay_hash` sequences. Changing `Event.replay_hash` or sharing metadata inside `Event.__post_init__` would change identity. #280 already owns the certification `json.dumps` skip. This lane stays a conformance / timing authority.

## Checks

- `python -m compileall` on exclusive files: ok
- `python -m pytest -q tests/test_integrated_replay_perf.py`: 6 passed
- Focused #279 stage/event-count contract reproduced here (17 events, expected stages)
- Full `tests/system/test_commercial_dry_run_replay_integration.py`: not run (TrustOS / CompanyOS / artifact-store not in the sparse tree)
- Ruff / session_finish / architecture / pr_readiness / GitHub CI: unavailable

Do not merge.
