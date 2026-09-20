# Integrated commercial replay performance verification

Lane: `REPLAY-CONFORMANCE-OWNER-V2`
PR: `#274` `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-arbitration-v2`
Status: draft, do not merge

## Verdict

| Question | Finding |
| --- | --- |
| Which path does #274 time? | **Commerce lifecycle only:** `builder()` → `run_dry_run_lifecycle` → `lifecycle_events` → `Event.replay_hash`. |
| Why 17 vs 37? | **Measurement scope, not hash drift.** 17 is the commerce projection. 37 is the unmerged #279 CLI concat of that projection plus fulfillment-risk events. |
| Does this-branch CLI concat fulfillment? | **No.** `scripts/run_commercial_replay_integration.py` on main/#274 is commerce-only. Concat lives on #279 HEAD `54aaa1a`. |
| Production `Event.replay_hash` changed? | **No.** Five-scenario aggregate hashes match the previously published set. |
| Production optimization applied? | **No.** #280 owns the laboratory and was not imported. |
| Isolated field-hash identity? | **Rejected.** |
| Canonical imports executed? | **Yes** (`classify_canonical()["status"] == "importable"`). |

## Call graph (from executable code)

```
#274 harness / main system test (17)
  SCENARIO_BUILDERS[i]()
    -> run_dry_run_lifecycle
    -> lifecycle_events  # 1 started + 15 LIFECYCLE_STEPS + 1 completed
    -> Event.replay_hash / replay_summary

#279 CLI only (`_replay_scenario` at 54aaa1a) (37)
  same 17 commerce events
    + run_fulfillment_risk_dry_run(customer_return_merchant_paid).events  # 20
    = tuple((*commerce_events, *fulfillment_events))  # 37
```

| Boundary | Function | Count | Owner |
| --- | --- | ---: | --- |
| Commerce dry-run trail | `evaluation.commerce.dry_run_events.lifecycle_events` | **17** | main + #279 `test_scenario_runs_through_real_builders_and_emits_a_clean_event_trail`; #274 harness |
| Fulfillment-risk trail | `run_fulfillment_risk_dry_run` on `customer_return_merchant_paid` | **20** | fulfillment module on main |
| Consolidated CLI trail | `tuple((*commerce_events, *fulfillment_events))` | **37** | **#279 CLI only** |

#274 asserts `event_count == 17` when imports succeed. Absorbing fulfillment into this harness would create a second replay spine. The 37 composition is classified by inspecting #279 CLI source and by counting the fulfillment module; the #279 runner is not copied.

Step suffixes: `started`, then `LIFECYCLE_STEPS` / `STEPS`, then `completed`.

## Live refs (this session)

- `main`: `e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6`
- #274 parent before this commit: `208991da43337446a477f985fc720f6ed12c5508`
- Prior complete module blob: `12df9826414c62a0355a79efda0df7f5aa38d8d5` (16,528 bytes, 411 lines) — not truncated
- #279 HEAD (read-only): `54aaa1a2773dc914e64fe6b0284f52134e184b55`
- #280 HEAD (read-only lab): `4565cca1212c5cce143680d246ba33032bd41362`

Exclusive worktree: `/tmp/marketos-pr274` on `grok/marketos-integrated-replay-performance-v1`. Canonical checkout `/tmp/marketos-src/MarketOS` stayed on clean `main`.

## Measurement methodology

- Path: commerce-only canonical dry-run (`execution_class=actual_canonical_dry_run`)
- Warm-up: 1 discarded run per scenario
- Repeats: 5 timed samples; report mean, min, max, p50, p95, p99 (linear interpolation)
- Identity: per-event `Event.replay_hash` plus aggregate SHA-256 of the concatenation of those hashes
- RSS: `/proc/self/status` VmRSS after each scenario
- Environment: Python 3.10.21, Linux glibc 2.36, timeout 30s
- #280 laboratory: not imported, not re-run

## Five-scenario commerce-only results

Evidence class = `actual`. Hashes are **byte-identical** to the prior published set.

| Scenario | Stage | Evidence | Events | Aggregate `Event.replay_hash` | p50 ms | p95 ms |
| --- | --- | --- | ---: | --- | ---: | ---: |
| hydroponics_positive_candidate | scale_candidate | observed | 17 | `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043` | 0.770 | 0.979 |
| smart_pet_support_burden_candidate | supplier_validated | observed | 17 | `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac` | 0.701 | 0.934 |
| solar_4g_security_blocked_candidate | economics_screened | fixture | 17 | `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9` | 0.687 | 0.733 |
| commodity_electronics_rejected_candidate | supplier_terms_pending | observed | 17 | `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4` | 0.682 | 0.735 |
| high_ticket_deferred_candidate | supplier_validated | observed | 17 | `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe` | 0.681 | 0.731 |

Invariants: hashes/IDs stable across repeats; `live_actions_taken == False`; solar remains `fixture`; no sequence issues; field hashes rejected as identity.

Timings are sandbox wall-clock (sub-millisecond dry-run). They are **not** production performance and are not #280 laboratory numbers.

## Verification

Executed in the exclusive #274 worktree unless noted:

- `pytest tests/test_integrated_replay_perf.py -v`: **13 passed in 1.08s** (status `actual`)
- `pytest tests/system/test_commercial_dry_run_replay_integration.py -q`: **32 passed in 0.97s** (main/#274 copy; 17-event trail)
- #279 read-only worktree `54aaa1a`: `test_scenario_runs_through_real_builders_and_emits_a_clean_event_trail` **5 passed**; `test_consolidated_replay_carries_research_through_mexico_fulfillment_and_safe_export` **5 passed** (37-event CLI)
- `pytest tests/contracts/test_architecture_boundaries.py -q`: **9 passed in 4.13s**
- `python -m compileall` / `ruff check` on owned files: clean
- `git diff --check`: clean

## Unavailable

- `grok` CLI / `--help` functions: not installed
- Hermes / `hermes verify`: not installed
- ECC benchmark skills: not installed
- CoderOS: not probed
- Colab: not used
- CI: `ci_unavailable` (hosted runner assignment is a separate lane)

Do not merge (draft PR).
