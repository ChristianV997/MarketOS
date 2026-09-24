# Commercial replay laboratory certification (#280)

Lane: `REPLAY-LAB-CANONICAL-INTEGRATION-CERTIFICATION`
PR: [#280](https://github.com/ChristianV997/MarketOS/pull/280) `antigravity/marketos-commercial-replay-benchmark-v1`
Schema: `commercial-replay-lab-benchmark-v3`
Status: draft, do not merge

## Ownership (refreshed this session)

| PR | Role | Branch | HEAD |
| --- | --- | --- | --- |
| #274 | conformance / Event-path arbitration | `grok/marketos-integrated-replay-performance-v1` | current mainline ancestry |
| #279 | canonical replay CLI | `codex/marketos-commercial-replay-consolidation-v1` | current mainline ancestry |
| #280 | laboratory | `antigravity/marketos-commercial-replay-benchmark-v1` | measured source head `1f6765613709b7641728cde4eb99ee38263e0d22` |
| main | base | `main` | `df160af1aad615dcdee7934bcd7122898eb5eff1` |

#274 and #279 files were not edited. `Event.replay_hash` was not edited.

## Execution class

Exclusive Windows worktree `C:\Users\HP\Documents\MarketOS.worktrees\marketos-commercial-replay-benchmark-v1` with materialized blobs. Sparse GitHub Contents API copies are not evidence.

- `grok` CLI, Hermes, ECC skills, and gstack: **unavailable** (not fabricated). CoderOS runtime checks were available but its OpenRouter free provider was unavailable.
- GitHub Actions: **`ci_unavailable`** (do not treat zero-step checks as executed tests).

## 17 versus 37 (from executable source)

```
commerce: builder() -> run_dry_run_lifecycle -> lifecycle_events
  1 commerce_dry_run_started
  + 15 LIFECYCLE_STEPS
  + 1 commerce_dry_run_completed
  = 17
  owner: main + #274 harness + #280 lab

#279 CLI _replay_scenario only (0dd4139):
  those 17
  + run_fulfillment_risk_dry_run(customer_return_merchant_paid).events  # 20
  = tuple((*commerce_events, *fulfillment_events))  # 37
```

This lab **refuses** a non-17 commerce trail. Comparing 17-event walls or hashes to 37-event rows is invalid.

On the current #280 tree, `scripts/run_commercial_replay_integration.py` is the canonical #279 concat CLI. The laboratory observes it without reimplementing its event construction. `run_canonical_replay_integration()` reports five 37-event rows and evaluates the 13-point safety invariants against the returned canonical fields.

Evidence class: the 17-event rows are deterministic dry-run/fixture evidence (`observed` or `fixture` as emitted by the builders); the 37-event rows are canonical replay integration evidence from the local CLI. Neither class is commercial validation.

## Tracked lab bytes (this tree, before this certifier commit they were already complete)

Previous HEAD `fd2f8ce7ac170159deb07fe7fe0099938e208877`:
- `scripts/benchmarks/benchmark_commercial_replay_lab.py` 55,143 bytes, blob `26bc9861fa5c115c636f65f5889989e58fc53a20`

Older reported SHAs `5545579` and `84aa84b` are ancestors, not the live head.

## Defects repaired in this certifier commit (lab + tests + docs only)

1. Commerce-only CLI cannot self-certify the 13-point #279 set.
2. `run_scenarios` raises on `event_count != 17`.
3. Full ordered `Event.replay_hash` sequences + aggregate SHA-256 are recorded and asserted against the published 17-event set.
4. `evidence_classification` follows builder `evidence_state` (`observed` is not rewritten to `fixture`; live states raise).
5. p95/p99 with n<20 are sample maxima (`sample_maximum_small_n_guard`).
6. Environment stamp: git HEAD, Python, platform, warmup, runs, scale_max.
7. Adversarial tests: altered intermediate hash, wrong counts 16/18/20/37, truncated module (real file), field-hash ≠ `Event.replay_hash`, empty-record vacuous pass closed.
8. Report narrative is generated from measured structs, not a hardcoded 13× PASS table.

`backend/events/replay_certification.py` is an existing canonical authority and was not changed by the laboratory finalization commit. No production optimization is claimed here; `Event.replay_hash` remains untouched.

## Measured replay evidence (current head)

Commands:

```
uv run --no-project --with scipy --with requests python scripts/benchmarks/benchmark_commercial_replay_lab.py --warmup 1 --runs 3 --scale-max 10 --json
uv run --no-project --with scipy --with requests python scripts/run_commercial_replay_integration.py --json
```

Environment: Python 3.13.15, Windows x86_64, benchmark warm-up=1 discarded, n=3 timed cycles, small-sample tails.

17-event commerce rows: 5 scenarios; every row emitted 17 events, equal ordered `Event.replay_hash` sequences, equal aggregate hashes between dual runs, and zero sequence/live-authority violations. The measured aggregate hashes are emitted in the JSON artifact; this report does not copy a stale hash table.

37-event canonical rows: 5 scenarios; every row emitted 37 events, `replay_equal=true`, launch authorization false, live actions false, and all 13 invariant checks true. The canonical authority is `scripts.run_commercial_replay_integration`; the laboratory invokes and observes it rather than duplicating it.

Benchmark timing: total timed runs 15; mean cycle 20.46 ms; p50 19.92 ms; p95/p99 22.71 ms. Because n=3 is below the tail threshold, p95 and p99 are sample maxima under `sample_maximum_small_n_guard`, not population tail estimates. Evidence is deterministic local dry-run/replay evidence, not commercial validation.

## Checks

| Check | Result |
| --- | --- |
| Exclusive #280 worktree | done (`antigravity/marketos-commercial-replay-benchmark-v1`) |
| `uv run --no-project --with pytest --with scipy --with requests pytest -q tests/benchmarks/test_lab_certification.py tests/benchmarks/test_commercial_replay_lab.py tests/system/test_commercial_dry_run_replay_integration.py` | 82 passed |
| `uv run --no-project --with pytest --with scipy --with requests pytest -q tests/system/test_commercial_dry_run_replay_integration.py tests/system/test_commercial_replay_evidence_truth_gaps.py` | 66 passed |
| `uv run --no-project --with ruff ruff check` on lab/tests | passed |
| `python -m compileall -q scripts/benchmarks evaluation/commerce tests/benchmarks tests/system` | passed |
| `git diff --check` | passed |
| Native `python -m pytest` | passed (21 benchmark tests passed; 97 total replay & architecture tests passed) |
| Native `python scripts/ai/session_finish.py --dry-run` | passed (6 passed; checks passed) |
| GitHub CI | failed zero-step/non-diagnostic checks; no application-specific pass inferred |
| OmniRoute/OpenRouter free pool | OpenRouter provider error; no model list; no delegated findings used |
| Merge | not performed |

## Safety

No providers, credentials, customer data, orders, payments, refunds, ads, messages, deployment, or live network mutations.

## Rollback

Revert the laboratory-only commit on `antigravity/marketos-commercial-replay-benchmark-v1`, or close draft #280. The base remains `df160af1aad615dcdee7934bcd7122898eb5eff1`.

## Operator next action

Keep #280 draft. Re-run the two measured commands above after any mainline or canonical replay change, then attach fresh JSON output to the PR before considering promotion. Do not merge.
