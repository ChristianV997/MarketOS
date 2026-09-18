# Integrated commercial replay performance

Lane: `INTEGRATED-REPLAY-PERFORMANCE-V1`
Branch: `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-perf-v1`
Status: draft, do not merge

## Scope

Measure the existing integrated commercial replay projection:

- `scripts/benchmark_commerce_cycle.py` — single-cycle dry-run latency (untouched)
- `scripts/run_commercial_replay_integration.py` — scenario replay (untouched)
- `evaluation/commerce/dry_run_events.lifecycle_events` — canonical Event projection
- `backend.contracts.events.Event.replay_hash` — full canonical JSON SHA-256

This lane does not score products, compute kernel money, emit a second event
spine, or call providers.

## Measured bottleneck

Authoring-sandbox Python 3.12, fixture candidates only.

| size | events | top stage | before pipeline ms | after pipeline ms | RSS KiB | replay prefix |
| ---: | ---: | --- | ---: | ---: | ---: | --- |
| 1 | 17 | hash_json_dumps 0.104 | 0.127 | 0.036 | 19004 | 1ba95137aa587e1f |
| 10 | 170 | hash_json_dumps 0.911 | 1.077 | 0.269 | 19388 | 19072ffd0dc24b46 |
| 100 | 1700 | hash_json_dumps 8.969 | 10.763 | 2.627 | 23228 | b293307ec5d4eea4 |
| 500 | 8500 | hash_json_dumps 46.856 | 59.011 | 13.795 | 36416 | bf6b5f2e88c8b9b6 |
| 1500 | 25500 | hash_json_dumps 144.323 | 205.353 | 56.375 | 58736 | 9f764135c51debfb |

At 1500 candidates the isolated stages were:

- `hash_json_dumps` 144.323 ms (mirrors `Event.replay_hash` / `canonical_json`)
- full before pipeline 205.353 ms
- full after pipeline 56.375 ms (~3.6x)

Top measured bottleneck: per-event `json.dumps` of the full envelope,
including the constant no-authority metadata block.

## Smallest compatible optimization

Isolated after-path only:

1. Indexed identity map for offer conflicts (equivalent to pairwise).
2. Shared metadata mapping instead of `dict(META)` per event.
3. Replay identity from event id + evidence fields, not full JSON.

Not done (would be a second authority or a contracts change):

- No cache.
- No parallel event spine.
- `Event.replay_hash` left unchanged. It still hashes the full envelope
  because metadata is part of the canonical contract.
- `evaluation/commerce/dry_run_events.py` left unchanged. `Event.__post_init__`
  already copies metadata through `_json_safe`, so sharing the source dict
  would not change production hashes.

## Equivalence proof

- Pairwise conflicts == indexed conflicts
- Copied-metadata event ids == shared-metadata event ids
- Evidence states preserved (`fixture` never upgrades to live attestation)
- After-path SHA-256 identity equal across repeats

Field hashes are **not** claimed equal to `Event.replay_hash`. They are the
isolated scale identity for this harness.

## Bounds

- `MAX_CANDIDATES = 2048`
- `MAX_EVENTS = 40000`
- `MAX_PAYLOAD_BYTES = 1 MiB` on sanitized input
- `TIMEOUT_MS = 8000`
- No network / provider calls

## Operator next action

On a disposable MarketOS worktree from `origin/main`:

```
git fetch origin --prune
git worktree add ... origin/grok/marketos-integrated-replay-performance-v1
python -m pytest -q tests/test_integrated_replay_perf.py
python scripts/run_integrated_replay_perf.py --json
```

Do not merge. Close the draft PR to roll back.
