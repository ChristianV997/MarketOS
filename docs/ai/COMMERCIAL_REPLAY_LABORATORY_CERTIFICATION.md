# Commercial replay laboratory certification (#280)

Lane: `REPLAY-LAB-CANONICAL-INTEGRATION-CERTIFICATION`
PR: [#280](https://github.com/ChristianV997/MarketOS/pull/280) `antigravity/marketos-commercial-replay-benchmark-v1`
Schema: `commercial-replay-lab-benchmark-v3`
Status: draft, do not merge

## Ownership (refreshed this session)

| PR | Role | Branch | HEAD |
| --- | --- | --- | --- |
| #274 | conformance / Event-path arbitration | `grok/marketos-integrated-replay-performance-v1` | `f51b746fad033a68d9c332c19784e9b2f045c9ce` |
| #279 | canonical replay CLI | `codex/marketos-commercial-replay-consolidation-v1` | `0dd413969b5c822f0bcbfa1764ea9fb9eecc9a57` |
| #280 | laboratory | `antigravity/marketos-commercial-replay-benchmark-v1` | this commit |
| main | base | `main` | `e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6` |

#274 and #279 files were not edited. `Event.replay_hash` was not edited.

## Execution class

Exclusive worktree `/tmp/marketos-pr280` with materialized blobs. Sparse GitHub Contents API copies are not evidence.

- `grok` CLI, Hermes, ECC skills, gstack, CoderOS: **unavailable** (not fabricated).
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

On this #280 tree, `scripts/run_commercial_replay_integration.py` is the **commerce-only** CLI (7442 bytes, no concat marker). Importing it is not a 13-point #279 pass. `run_canonical_replay_integration()` returns `status=commerce_only_cli_not_pr279`, `all_invariants_satisfied=False`.

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

`backend/events/replay_certification.py` three-line advisory-only `json.dumps` patch is left in place (semantically equivalent; `Event.replay_hash` unchanged). No further production optimization.

## Measured 17-event aggregate `Event.replay_hash` (this run)

Command:

```
python3 scripts/benchmarks/benchmark_commercial_replay_lab.py --warmup 2 --runs 5 --scale-max 50 --json
```

Environment: Python 3.10.21, Linux x86_64, warmup=2 discarded, n=5 timed cycles, small-sample tails.

| Scenario | Evidence | Events | Aggregate `Event.replay_hash` | Dual-run equal |
| --- | --- | ---: | --- | --- |
| hydroponics_positive_candidate | observed | 17 | `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043` | True |
| smart_pet_support_burden_candidate | observed | 17 | `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac` | True |
| solar_4g_security_blocked_candidate | fixture | 17 | `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9` | True |
| commodity_electronics_rejected_candidate | observed | 17 | `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4` | True |
| high_ticket_deferred_candidate | observed | 17 | `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe` | True |

These match the #274 published 17-event aggregates. Hash drift across 5 warmed cycles: **none**.

Statistical (n=5, sample maxima): mean 4.87 ms, p50 4.86 ms, p95=p99=max 4.91 ms. Fixture/dry-run walls, not commercial validation.

## Checks

| Check | Result |
| --- | --- |
| Exclusive #280 worktree | done (`antigravity/marketos-commercial-replay-benchmark-v1`) |
| `python -m pytest tests/benchmarks/test_lab_certification.py tests/benchmarks/test_commercial_replay_lab.py` | 21 passed |
| `python -m pytest tests/system/test_commercial_dry_run_replay_integration.py tests/system/test_public_signal_replay_certification.py` (#280 / main 17-path) | 33 passed |
| `python -m pytest tests/system/test_commercial_dry_run_replay_integration.py` in #279-ro @ `0dd4139` | 61 passed |
| `python -m pytest tests/contracts/test_architecture_boundaries.py` | 9 passed |
| `python -m compileall` + `ruff check` on lab/tests | ok |
| `git diff --check` | clean |
| `python scripts/ai/session_finish.py --dry-run` | ok |
| GitHub CI | `ci_unavailable` |
| grok / Hermes / ECC / gstack / CoderOS | unavailable |
| Merge | not performed |

## Safety

No providers, credentials, customer data, orders, payments, refunds, ads, messages, deployment, or live network mutations.

## Rollback

Revert this certifier commit on `antigravity/marketos-commercial-replay-benchmark-v1` or close draft #280. Base remains `e6a2e88e`.

## Operator next action

Keep #280 draft. After #279 merges, re-run `run_canonical_replay_integration()` on the concat CLI and only then consider the 13-point set. Do not merge.
