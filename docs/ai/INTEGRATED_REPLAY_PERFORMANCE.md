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

## Live refs (this session, do not reuse stale snapshots)

- `main`: `e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6`
- #274 prior HEAD: `ccd4ec7ab7ead327f269e3c0d958e985db6bbd09`
- #279 HEAD (read-only): `b07d465f40e2ef7174b706b369645ba9c44df0fb`
- #280 HEAD (read-only lab): `4565cca1212c5cce143680d246ba33032bd41362`

This sandbox cannot clone MarketOS. Composite worktree unavailable. Event counts above are from live source of `lifecycle_events` and the #279 CLI `_replay_scenario` concat, plus #279's own `== 17` system assertion. Historical worktree hash table is not commercial validation.

## Five-scenario commerce-only measurements (historical worktree; not re-run here)

Evidence class = `actual_canonical_dry_run` when imports exist. #280 walls were **not** re-executed.

| Scenario | Stage | Evidence | Events | Aggregate `Event.replay_hash` |
| --- | --- | --- | ---: | --- |
| hydroponics_positive_candidate | scale_candidate | observed | 17 | `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043` |
| smart_pet_support_burden_candidate | supplier_validated | observed | 17 | `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac` |
| solar_4g_security_blocked_candidate | economics_screened | fixture | 17 | `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9` |
| commodity_electronics_rejected_candidate | supplier_terms_pending | observed | 17 | `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4` |
| high_ticket_deferred_candidate | supplier_validated | observed | 17 | `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe` |

Invariants: hashes/IDs stable across repeats; no live actions; `live_attestation=False`; solar stays `fixture`. #279 latest CLI guard marks missing supplier cost/shipping as `unavailable` / `evidence_state=missing` instead of publishing zeroed kernel arithmetic. That guard lives in the CLI, not in `lifecycle_events`, so it does not change the 17-event commerce count.

## Missing-cost / evidence after #279 guard

- Commerce `lifecycle_events` still emits one event per report step even when `unit_economics` status is `unavailable`.
- Count stays 17.
- CLI 37-event trail still concatenates fulfillment independently of that guard.

## Checks

- `python -m pytest -q tests/test_integrated_replay_perf.py` (artifact / unavailable-import branch: 7 passed)
- #279 system test and #280 lab: not executed in this sandbox (no composite tree)
- GitHub CI: zero-step / `runner_id: 0` class; not executed tests
- Ruff / session_finish / CoderOS / ECC / gstack / Hermes / Colab: unavailable or not invoked

Do not merge.
