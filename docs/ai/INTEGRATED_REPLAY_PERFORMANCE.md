# Integrated commercial replay performance verification

Lane: `REPLAY-17-VS-37-EVENT-CONTRACT-RECONCILIATION-V3`
PR: `#274` `grok/marketos-integrated-replay-performance-v1`
Schema: `integrated-replay-arbitration-v2`
Status: draft, do not merge

## Verdict

| Question | Finding |
| --- | --- |
| Which path is canonical for #274 timing? | **Commerce lifecycle only:** `builder()` → `run_dry_run_lifecycle` → `lifecycle_events` → `Event.replay_hash`. |
| Why did reports say 17 vs 37? | **Measurement scope, not hash drift.** 17 is the commerce projection. 37 is the #279 CLI concat of that projection plus fulfillment-risk events. |
| Same builders? | Same five public names. #279 CLI then overlays research fixtures + fulfillment `customer_return_merchant_paid`. |
| Production `Event.replay_hash` changed? | **No.** |
| Production optimization applied? | **No.** #280 owns the laboratory. |
| Isolated field-hash identity? | **Rejected.** |
| Were published #280 numbers re-run? | **No.** |

## Comparable boundary (locked)

| Boundary | Function | Event count | Owner |
| --- | --- | ---: | --- |
| Commerce dry-run trail | `evaluation.commerce.dry_run_events.lifecycle_events` | **17** = 1 `started` + 15 steps + 1 `completed` | #279 system test `test_scenario_runs_through_real_builders_and_emits_a_clean_event_trail`; #274 harness |
| Fulfillment-risk trail | `run_fulfillment_risk_dry_run(...).events` on `customer_return_merchant_paid` | **20** | fulfillment module on main / #279 CLI |
| Consolidated CLI trail | `tuple((*commerce_events, *fulfillment_events))` in `scripts/run_commercial_replay_integration.py` | **37** = 17 + 20 | #279 CLI only |

#274 must keep asserting `event_count == 17` when imports succeed. Absorbing fulfillment into this harness would create a second replay spine.

Commerce step order (`STEPS` in `evaluation/perf/integrated_replay.py`, matching `lifecycle_events` over `report.steps`):

`evidence`, `supplier_offer`, `market_lane`, `unit_economics`, `competition`, `promotion_gate`, `offer`, `experiment_draft`, `campaign_draft`, `simulated_order`, `supplier_dispatch_draft`, `tracking_draft`, `delivery`, `return_rma`, `contribution_reconciliation`.

IDs: `{scenario_id}:started`, `{scenario_id}:{step}`, `{scenario_id}:completed`.

## Live refs (this session)

- `main`: `e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6`
- #274 HEAD: `ba8794d1d249ac102d33056dfb64d763f5d952d8`
- #279 HEAD (read-only): `c8cab13854cb593da20d200f16b7c7e44c22fd3e`
- #280 HEAD (read-only lab): `4565cca1212c5cce143680d246ba33032bd41362`

Verified in full exclusive worktree `C:/Users/HP/Documents/MarketOS.worktrees/marketos-pr274-replay-conformance` on branch `grok/marketos-integrated-replay-performance-v1`. Canonical module `evaluation/perf/integrated_replay.py` is byte-verified from repository object `12df9826414c62a0355a79efda0df7f5aa38d8d5` (16,528 bytes, 412 lines).

## Five-scenario commerce-only measurements (live canonical dry-run path)

Evidence class = `actual_canonical_dry_run`. Timed across 5 repeats per scenario. #280 benchmark laboratory remained read-only.

| Scenario | Stage | Evidence | Events | Aggregate `Event.replay_hash` |
| --- | --- | --- | --- | ---: |
| hydroponics_positive_candidate | scale_candidate | observed | 17 | `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043` |
| smart_pet_support_burden_candidate | supplier_validated | observed | 17 | `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac` |
| solar_4g_security_blocked_candidate | economics_screened | fixture | 17 | `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9` |
| commodity_electronics_rejected_candidate | supplier_terms_pending | observed | 17 | `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4` |
| high_ticket_deferred_candidate | supplier_validated | observed | 17 | `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe` |

Invariants certified:
- Hashes and event IDs are 100% stable across repeats.
- `live_actions_taken == False` and `live_attestation == False` across all runs; solar remains `fixture`.
- Zero sequence issues and zero live authority violations detected.
- Replay identity strictly uses `Event.replay_hash` sequences; isolated field hashes are explicitly rejected.

## 17 vs 37 Event Contract Certification

- **Commerce Sub-Lifecycle**: Emits exactly 17 events (`started` + 15 domain steps + `completed`) via `evaluation.commerce.dry_run_events.lifecycle_events`.
- **Fulfillment-Risk Lifecycle**: `customer_return_merchant_paid` emits exactly 20 events via `evaluation.commerce.fulfillment_risk_lifecycle.run_fulfillment_risk_dry_run`.
- **Consolidated #279 CLI**: Concatenates `(*commerce_events, *fulfillment_events)` producing 37 events (17 + 20).
- **Ownership**: #274 owns only the timing and conformance seam for the 17 commerce events; it explicitly does not absorb fulfillment into its harness to avoid becoming a second replay spine.

## Verification & Validation Suite Results

Executed in the full exclusive worktree:
- `python -m pytest tests/test_integrated_replay_perf.py -v`: **7 passed in 88.13s** (active canonical path, status: `actual`)
- `python -m pytest tests/system/test_commercial_dry_run_replay_integration.py -v`: **32 passed in 7.71s**
- `python -m pytest tests/contracts/test_architecture_boundaries.py -q`: **9 passed in 23.44s**
- `python -m compileall -q evaluation/perf/integrated_replay.py scripts/run_integrated_replay_perf.py tests/test_integrated_replay_perf.py`: **0 errors**
- `python -m ruff check evaluation/perf/integrated_replay.py scripts/run_integrated_replay_perf.py tests/test_integrated_replay_perf.py`: **All checks passed**
- `git diff --check`: **Clean (code 0)**
- `python scripts/ai/session_finish.py --dry-run`: **6 passed in 0.76s**
- `python scripts/ai/pr_readiness_report.py --json`: **merge_readiness: clear, 0 blocking warnings**

## Colab & Cloud Resource Policy

Colab resources were not spent. The complete test suite and scenario measurements executed deterministically in ~88s locally within the private worktree. Allocating 200 compute units for a smoke test or copying private payloads to external notebooks was unnecessary and contrary to safety policy.

Do not merge (draft PR).
