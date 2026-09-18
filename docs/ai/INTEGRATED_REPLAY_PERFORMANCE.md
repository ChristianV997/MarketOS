# Integrated commercial replay performance arbitration

Lane: `REPLAY-PERFORMANCE-CANONICAL-ARBITRATION-V2`
PR: `#274` `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-arbitration-v2`
Status: draft, do not merge

## Verdict

| Question | Finding |
| --- | --- |
| Which path is canonical? | **#279** — five fixture builders, `run_dry_run_lifecycle`, `lifecycle_events`, `Event.replay_hash`, `replay_summary`. |
| Does #274 measure real commercial replay? | Only when those imports succeed. This sandbox classifies them **unavailable**. On an operator worktree the seam drives the five builders and times `Event.replay_hash`, it does not invent events. |
| Does #280 duplicate #274 scope? | **#280 owns the laboratory** (7D sensitivity, cProfile, scale lab, certification `json.dumps` skip for non-advisory events). #274 must not copy those files. |
| Did any optimization change `Event.replay_hash`? | **No.** Field-hash is rejected as identity. `Event.canonical_json` remains the envelope hash. |
| Event ids / sequence / payload / evidence? | Canonical path preserves them through `lifecycle_events` + `replay_summary`. Isolated dict projection is not that path. |
| Does the isolated 3.6x survive real imports? | **No.** The 205.353 ms → 56.375 ms number hashed synthetic field strings. `Event.__post_init__` still copies metadata and `replay_hash` still dumps the full envelope. |

## Why no production optimization in this PR

A production change is allowed only if baseline and optimized paths consume the same canonical inputs and keep identical `Event.replay_hash` sequences.

Sharing `_NO_AUTHORITY_METADATA` in `dry_run_events.py` does not help: `Event` re-copies metadata through `_json_safe`. Changing `Event.replay_hash` would change existing hashes. #280 already owns the only measured certification skip (`assert_no_live_authority` dumps JSON only for `aggregate_type == "advisory"`). This lane therefore applies **no** production patch.

## What #274 now is

Conformance / arbitration for the #279 Event path:

- classify canonical imports;
- when importable, run the five builders twice and require equal event ids, equal `Event.replay_hash` sequences, clean sequence, zero live-authority violations, fixture evidence that cannot upgrade to live;
- reject isolated field-hash as identity;
- record that #280 remains the laboratory owner.

## Operator next action

```
git fetch origin --prune
git worktree add ... origin/grok/marketos-integrated-replay-performance-v1
python -m pytest -q tests/test_integrated_replay_perf.py
python scripts/run_integrated_replay_perf.py --json
```

Optional combined check with #279 (do not copy #280 files into this branch):

```
python -m pytest -q tests/test_integrated_replay_perf.py tests/system/test_commercial_dry_run_replay_integration.py
```

Do not merge. Close the draft PR to roll back.
