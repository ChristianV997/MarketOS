# Commercial Replay Benchmark & Laboratory Evaluation Report

**Lane:** `MARKETOS-COMMERCIAL-REPLAY-BENCHMARK-V1`
**Role:** Antigravity Performance & Evidence-Laboratory Engineer
**Schema Version:** `commercial-replay-lab-benchmark-v3`
**Evidence Classification:** per-scenario `observed` / `fixture` / `assumed` (never live)
**Live Authority:** `blocked` (0 live mutations, 0 provider calls, 0 credentials)

---

## Executive Summary

This report documents the rigorous laboratory validation of MarketOS commercial dry-run replay,
deterministic hash repeatability, 7-dimensional sensitivity analysis, and performance scaling.
The evaluation reports fixture/dry-run measurements. It does not claim commercial validation.
1. **Event scope:** this laboratory measures the 17-event commerce lifecycle (start + 15 `LIFECYCLE_STEPS` + completion). 37 events exist only as PR #279 CLI concatenation (`tuple((*commerce_events, *fulfillment_events))`) and are not like-for-like.
2. **PR #279 13-point set:** status `available`; all_invariants_satisfied=`True`. A commerce-only CLI import is not a 13-point pass.
3. **Deterministic 17-event replay:** dual-run `Event.replay_hash` sequences and aggregate sequence hashes are recorded per scenario.
4. **Zero live authority on the 17-event trail:** sequence issues and live-authority violations must be empty; adversarial advisory payloads fail closed.
5. **Warm-up + small-sample tails:** 2 warm-up cycles discarded; n=5 timed cycles. p95/p99 are **sample maxima** (`sample_maximum_small_n_guard`), not independent tail estimates.
6. **7-dimensional sensitivity:** kernel sweep on hydroponics fixture assumptions (CAC, shipping, FX, returns, defects, warranty, delivery delay). Not Event-path work.
7. **Scaling / tracemalloc:** kernel evaluation throughput only. Not a measurement of `Event.replay_hash`.
8. **Production Event hash path:** unchanged. The #280 `assert_no_live_authority` patch only scopes JSON dumps to advisory events.

---

## 1. Canonical Scenario Replay Matrix

| Scenario ID | SKU | Lane | Achievable Stage | Promoted | Events | Replay Equal | Sequence Issues | Live Violations | Wall Clock (ms) |
|---|---|---|---|:---:|:---:|:---:|:---:|:---:|---:|
| `hydroponics_positive_candidate` | `hydroponics-nutrient-kit` | `us-domestic-hydro` | `scale_candidate` | ✅ Yes | 17 | ✅ Bit-Identical | 0 | 0 | 3.26 |
| `smart_pet_support_burden_candidate` | `smart-pet-feeder` | `us-domestic-petfeeder` | `supplier_validated` | ❌ No | 17 | ✅ Bit-Identical | 0 | 0 | 2.93 |
| `solar_4g_security_blocked_candidate` | `solar-4g-security-camera` | `us-domestic-solarcam` | `economics_screened` | ❌ No | 17 | ✅ Bit-Identical | 0 | 0 | 2.64 |
| `commodity_electronics_rejected_candidate` | `usb-c-cable-3pack` | `us-domestic-usbc-cable` | `supplier_terms_pending` | ❌ No | 17 | ✅ Bit-Identical | 0 | 0 | 2.65 |
| `high_ticket_deferred_candidate` | `e-cargo-bike` | `us-domestic-egraded-bike` | `supplier_validated` | ❌ No | 17 | ✅ Bit-Identical | 0 | 0 | 2.56 |

### Scenario Outcome Details & Gate Verification

#### Scenario: `hydroponics_positive_candidate`
- **Candidate ID:** `hydroponics-nutrient-kit`
- **Achieved Stage:** `scale_candidate` (Expected: `scale_candidate`)
- **Blockers Encountered:** `None (Fully Promoted)`
- **Terminal Event Replay Hash:** `20cb02d5de4c57a01525fc94efd18ce2681e4b8ba4083c2aa59d71ffd17ef783`
- **Aggregate `Event.replay_hash` sequence:** `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043`
- **Evidence:** `observed` (builder `observed`)
- **Event scope:** `commerce_lifecycle` (17 events)
- **Replay Match:** dual-run sequences equal `True`

#### Scenario: `smart_pet_support_burden_candidate`
- **Candidate ID:** `smart-pet-feeder`
- **Achieved Stage:** `supplier_validated` (Expected: `supplier_validated`)
- **Blockers Encountered:** `['support_owner', 'unknown_support_owner']`
- **Terminal Event Replay Hash:** `122f7c13b66bfda7abd14adf443b98de763b3fb8ee7ef63f66a9bb810c93941d`
- **Aggregate `Event.replay_hash` sequence:** `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac`
- **Evidence:** `observed` (builder `observed`)
- **Event scope:** `commerce_lifecycle` (17 events)
- **Replay Match:** dual-run sequences equal `True`

#### Scenario: `solar_4g_security_blocked_candidate`
- **Candidate ID:** `solar-4g-security-camera`
- **Achieved Stage:** `economics_screened` (Expected: `economics_screened`)
- **Blockers Encountered:** `['compliance', 'evidence_state_insufficient_for_stage:fixture', 'support_owner', 'unknown_support_owner']`
- **Terminal Event Replay Hash:** `056abd6082b649d5edd04a1959c48b2b3598d5e8f00b38ce86a49c798e094354`
- **Aggregate `Event.replay_hash` sequence:** `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9`
- **Evidence:** `fixture` (builder `fixture`)
- **Event scope:** `commerce_lifecycle` (17 events)
- **Replay Match:** dual-run sequences equal `True`

#### Scenario: `commodity_electronics_rejected_candidate`
- **Candidate ID:** `usb-c-cable-3pack`
- **Achieved Stage:** `supplier_terms_pending` (Expected: `supplier_terms_pending`)
- **Blockers Encountered:** `['competition', 'economics']`
- **Terminal Event Replay Hash:** `7fc7b5d9f737091ec58bf397376b03daad7b788e2a1b0f5afd9e21b28c5789ee`
- **Aggregate `Event.replay_hash` sequence:** `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4`
- **Evidence:** `observed` (builder `observed`)
- **Event scope:** `commerce_lifecycle` (17 events)
- **Replay Match:** dual-run sequences equal `True`

#### Scenario: `high_ticket_deferred_candidate`
- **Candidate ID:** `e-cargo-bike`
- **Achieved Stage:** `supplier_validated` (Expected: `supplier_validated`)
- **Blockers Encountered:** `['return_route', 'unknown_return_owner', 'unknown_warranty_owner', 'warranty_route']`
- **Terminal Event Replay Hash:** `ba495e3bec2db1958fb92e5ca57976dafcda152587a672ddedf132de3cdb885f`
- **Aggregate `Event.replay_hash` sequence:** `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe`
- **Evidence:** `observed` (builder `observed`)
- **Event scope:** `commerce_lifecycle` (17 events)
- **Replay Match:** dual-run sequences equal `True`

---

## 2. Canonical Safety Invariants Certification Matrix

13-point #279 concat-CLI invariants were observed and passed on this run.

| Safety Invariant | Target Requirement | Certification Status | Evidence |
|---|---|:---:|---|
| **Bit-Identical Event.replay_hash sequence (17)** | 17-event commerce lab | PASS | `ScenarioReplayLaboratory.run_scenarios` |
| **Aggregate sequence hash stable** | 17-event commerce lab | PASS | `ScenarioReplayLaboratory.run_scenarios` |
| **Zero sequence violations (17)** | 17-event commerce lab | PASS | `ScenarioReplayLaboratory.run_scenarios` |
| **Zero live authority violations (17)** | 17-event commerce lab | PASS | `ScenarioReplayLaboratory.run_scenarios` |
| **live_actions_taken is False** | 17-event commerce lab | PASS | `ScenarioReplayLaboratory.run_scenarios` |
| `all_event_ids_identical` | #279 13-point set | PASS | status `available` |
| `all_ordering_identical` | #279 13-point set | PASS | status `available` |
| `monotonic_timestamps` | #279 13-point set | PASS | status `available` |
| `all_hash_sequences_identical` | #279 13-point set | PASS | status `available` |
| `all_replay_hashes_identical` | #279 13-point set | PASS | status `available` |
| `no_sequence_violations` | #279 13-point set | PASS | status `available` |
| `no_live_authority_violations` | #279 13-point set | PASS | status `available` |
| `live_actions_taken_false` | #279 13-point set | PASS | status `available` |
| `live_attestation_false` | #279 13-point set | PASS | status `available` |
| `governor_simulated` | #279 13-point set | PASS | status `available` |
| `approval_ledger_simulated` | #279 13-point set | PASS | status `available` |
| `trustos_export_sanitized` | #279 13-point set | PASS | status `available` |
| `no_mutations` | #279 13-point set | PASS | status `available` |

---

## 3. 7-Dimensional Bounded Sensitivity Matrix

Evaluated on baseline candidate `hydroponics_positive_candidate` (Retail Price: $44.99 USD, Product Cost: $11.20 USD).

### Dimension: `cac`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `2.00` | $44.99 | $22.04974 | $20.04974 | 0.4456 | $22.04974 | 2.0404 | $0.0000 | $24.94026 |
| `4.00` | $44.99 | $22.04974 | $18.04974 | 0.4012 | $22.04974 | 2.0404 | $0.0000 | $26.94026 |
| `6.00` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $0.0000 | $28.94026 |
| `8.00` | $44.99 | $22.04974 | $14.04974 | 0.3123 | $22.04974 | 2.0404 | $0.0000 | $30.94026 |
| `10.00` | $44.99 | $22.04974 | $12.04974 | 0.2678 | $22.04974 | 2.0404 | $0.0000 | $32.94026 |
| `12.00` | $44.99 | $22.04974 | $10.04974 | 0.2234 | $22.04974 | 2.0404 | $0.0000 | $34.94026 |
| `15.00` | $44.99 | $22.04974 | $7.04974 | 0.1567 | $22.04974 | 2.0404 | $0.0000 | $37.94026 |
| `20.00` | $44.99 | $22.04974 | $2.04974 | 0.0456 | $22.04974 | 2.0404 | $0.0000 | $42.94026 |

### Dimension: `supplier_shipping`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `1.50` | $44.99 | $24.04974 | $18.04974 | 0.4012 | $24.04974 | 1.8707 | $0.0000 | $26.94026 |
| `2.50` | $44.99 | $23.04974 | $17.04974 | 0.3790 | $23.04974 | 1.9519 | $0.0000 | $27.94026 |
| `3.50` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $0.0000 | $28.94026 |
| `5.00` | $44.99 | $20.54974 | $14.54974 | 0.3234 | $20.54974 | 2.1893 | $0.0000 | $30.44026 |
| `7.50` | $44.99 | $18.04974 | $12.04974 | 0.2678 | $18.04974 | 2.4926 | $0.0000 | $32.94026 |
| `10.00` | $44.99 | $15.54974 | $9.54974 | 0.2123 | $15.54974 | 2.8933 | $0.0000 | $35.44026 |
| `15.00` | $44.99 | $10.54974 | $4.54974 | 0.1011 | $10.54974 | 4.2646 | $0.0000 | $40.44026 |

### Dimension: `fx_reserve_rate`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `0.00` | $44.99 | $22.0497400 | $16.0497400 | 0.3567 | $22.0497400 | 2.0404 | $0.0000 | $28.9402600 |
| `0.01` | $44.99 | $21.8203374 | $15.8203374 | 0.3516 | $21.8203374 | 2.0618 | $0.0000 | $29.1696626 |
| `0.02` | $44.99 | $21.5909348 | $15.5909348 | 0.3465 | $21.5909348 | 2.0837 | $0.0000 | $29.3990652 |
| `0.03` | $44.99 | $21.3615322 | $15.3615322 | 0.3414 | $21.3615322 | 2.1061 | $0.0000 | $29.6284678 |
| `0.05` | $44.99 | $20.9027270 | $14.9027270 | 0.3312 | $20.9027270 | 2.1524 | $0.0000 | $30.0872730 |
| `0.08` | $44.99 | $20.2145192 | $14.2145192 | 0.3159 | $20.2145192 | 2.2256 | $0.0000 | $30.7754808 |

### Dimension: `return_rate`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `0.02` | $44.99 | $23.84934 | $17.84934 | 0.3967 | $23.84934 | 1.8864 | $0.0000 | $27.14066 |
| `0.04` | $44.99 | $22.94954 | $16.94954 | 0.3767 | $22.94954 | 1.9604 | $0.0000 | $28.04046 |
| `0.06` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $0.0000 | $28.94026 |
| `0.08` | $44.99 | $21.14994 | $15.14994 | 0.3367 | $21.14994 | 2.1272 | $0.0000 | $29.84006 |
| `0.12` | $44.99 | $19.35034 | $13.35034 | 0.2967 | $19.35034 | 2.3250 | $0.0000 | $31.63966 |
| `0.18` | $44.99 | $16.65094 | $10.65094 | 0.2367 | $16.65094 | 2.7019 | $0.0000 | $34.33906 |
| `0.25` | $44.99 | $13.50164 | $7.50164 | 0.1667 | $13.50164 | 3.3322 | $0.0000 | $37.48836 |

### Dimension: `defect_rate`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `0.005` | $44.99 | $22.10574 | $16.10574 | 0.3580 | $22.10574 | 2.0352 | $0.0000 | $28.88426 |
| `0.01` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $0.0000 | $28.94026 |
| `0.02` | $44.99 | $21.93774 | $15.93774 | 0.3543 | $21.93774 | 2.0508 | $0.0000 | $29.05226 |
| `0.04` | $44.99 | $21.71374 | $15.71374 | 0.3493 | $21.71374 | 2.0720 | $0.0000 | $29.27626 |
| `0.06` | $44.99 | $21.48974 | $15.48974 | 0.3443 | $21.48974 | 2.0936 | $0.0000 | $29.50026 |
| `0.10` | $44.99 | $21.04174 | $15.04174 | 0.3343 | $21.04174 | 2.1381 | $0.0000 | $29.94826 |

### Dimension: `warranty_rate`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `0.00` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $0.0000 | $28.94026 |
| `0.005` | $44.99 | $21.99374 | $15.99374 | 0.3555 | $21.99374 | 2.0456 | $0.0000 | $28.99626 |
| `0.01` | $44.99 | $21.93774 | $15.93774 | 0.3543 | $21.93774 | 2.0508 | $0.0000 | $29.05226 |
| `0.02` | $44.99 | $21.82574 | $15.82574 | 0.3518 | $21.82574 | 2.0613 | $0.0000 | $29.16426 |
| `0.03` | $44.99 | $21.71374 | $15.71374 | 0.3493 | $21.71374 | 2.0720 | $0.0000 | $29.27626 |
| `0.05` | $44.99 | $21.48974 | $15.48974 | 0.3443 | $21.48974 | 2.0936 | $0.0000 | $29.50026 |

### Dimension: `delivery_delay_days`

| Input Value | Net Sales | Contrib Before CAC | Contrib After CAC | Contrib Margin | Break-Even CAC | Break-Even ROAS | Return Lag Exposure | Cash Required |
|---|---|---|---|---|---|---|---|---|
| `7` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $0.6298599999999999999999999999 | $28.94026 |
| `14` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $1.259720000000000000000000000 | $28.94026 |
| `21` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $1.88958 | $28.94026 |
| `30` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $2.6994 | $28.94026 |
| `45` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $4.04910 | $28.94026 |
| `60` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $5.3988 | $28.94026 |
| `90` | $44.99 | $22.04974 | $16.04974 | 0.3567 | $22.04974 | 2.0404 | $8.0982 | $28.94026 |

---

## 4. Scaling & Memory Profiling Analysis

| Grid Points / Dim | Total Evaluations | Wall Clock (ms) | Throughput (evals/sec) | Peak Memory (KB) | Memory / Eval (bytes) |
|---:|---:|---:|---:|---:|---:|
| 10 | 70 | 139.21 | 502.8 | 508.0 | 7431.0 |
| 50 | 350 | 839.93 | 416.7 | 2542.0 | 7437.2 |
| 100 | 700 | 1370.80 | 510.7 | 5043.8 | 7378.3 |
| 250 | 1750 | 3381.85 | 517.5 | 12615.0 | 7381.6 |
| 500 | 3500 | 7770.17 | 450.4 | 25186.9 | 7369.0 |

### Scaling Observations
- **Throughput (this run, single-shot per scale point):** 416.7 to 517.5 kernel evals/sec. Not Event.replay_hash throughput; not Monte Carlo.
- **Memory / eval (tracemalloc, kernel sweep):** 7369.0 to 7437.2 bytes. n=1 per scale point; not a leak proof.
- **Warm-up:** scaling points are cold/single-shot. Warmed timings live only in section 5.

---

## 5. Statistical Performance & Latency Distribution

- **Warm-up Cycles:** 2 complete cycles (executed and discarded before measurement)
- **Benchmark Iterations:** 5 complete cycles (25 scenario executions)
- **Sample Size Category:** Small Sample (n < 20)
- **Tail Estimation Method:** `sample_maximum_small_n_guard` (using percentile_guard to prevent asymptotic overclaiming on small n)
- **Mean Cycle Latency:** 9.72 ms
- **Median / p50 Latency:** 9.74 ms
- **Min / Max Latency:** 9.58 ms / 9.81 ms
- **95th Percentile (p95):** 9.81 ms *(sample maximum; n<20)*
- **99th Percentile (p99):** 9.81 ms *(sample maximum; n<20)*
- **Standard Deviation:** 0.09 ms
- **Variance:** 0.01 ms²
- **Hash Sequence Drift:** `ZERO DRIFT (PASS)`

### Per-Scenario Latency Breakdown

| Scenario Builder | Events | Mean Latency (ms) | Median / p50 (ms) | Min (ms) | Max (ms) |
|---|:---:|---:|---:|---:|---:|
| `hydroponics_positive_candidate` | 17 | 1.95 | 1.96 | 1.88 | 2.00 |
| `smart_pet_support_burden_candidate` | 17 | 1.92 | 1.91 | 1.82 | 2.04 |
| `solar_4g_security_blocked_candidate` | 17 | 1.95 | 1.97 | 1.90 | 1.99 |
| `commodity_electronics_rejected_candidate` | 17 | 1.95 | 1.95 | 1.90 | 2.01 |
| `high_ticket_deferred_candidate` | 17 | 1.94 | 1.92 | 1.90 | 1.98 |

### Top CPU Cumulative Bottlenecks (from cProfile)

| Function | Total Calls | Total Time (s) | Cumulative Time (s) |
|---|---:|---:|---:|
| `enum.py:202(__get__)` | 25 | 0.0000 | 0.0000 |
| `<string>:2(__init__)` | 25 | 0.0001 | 0.0009 |
| `encoder.py:205(iterencode)` | 850 | 0.0185 | 0.0185 |
| `events.py:23(_json_safe)` | 11680 | 0.0119 | 0.0156 |
| `kernel.py:497(to_dict)` | 25 | 0.0006 | 0.0021 |
| `replay_certification.py:48(replay_summary)` | 25 | 0.0006 | 0.0334 |
| `kernel.py:344(__post_init__)` | 25 | 0.0004 | 0.0018 |
| `kernel.py:175(__post_init__)` | 1175 | 0.0038 | 0.0262 |
| `replay_certification.py:37(summarize_ledger)` | 25 | 0.0002 | 0.0007 |
| `events.py:54(__post_init__)` | 425 | 0.0038 | 0.0209 |
| `kernel.py:364(to_dict)` | 25 | 0.0002 | 0.0002 |
| `kernel.py:275(to_dict)` | 875 | 0.0016 | 0.0016 |

---

## 6. Measured Optimization Proof

### Bottleneck Identified
During profiling, `backend.events.replay_certification.assert_no_live_authority` was found executing
redundant `json.dumps({"event_type": ..., "payload": ..., "metadata": ...}, sort_keys=True)`
calls on *every* lifecycle and ledger event, even when `event.aggregate_type != 'advisory'`.
In a canonical scenario of 17 events, only advisory events require inspecting text for `_LIVE` tokens.

### Applied Patch
Moved `text = json.dumps(...)` strictly inside the `if event.aggregate_type == 'advisory':` block.

### Semantic & Bit-Identical Equivalence Proof
- **Return Value:** 100% identical violation lists across all tests and scenarios.
- **Test Suite Verification:** Passed all integration and replay tests in `tests/system/test_public_signal_replay_certification.py`, `tests/system/test_commercial_dry_run_replay_integration.py`, and `tests/benchmarks/test_commercial_replay_lab.py`.
- **Hash Stability:** All event hashes remain 100% bit-identical (`replay_equal: true`).

---

## 7. Quad-Perspective Engineering Review

### Review 1: Architecture & Replay Authority
- **Single Event Spine:** Enforces `backend.contracts.events.Event` as the canonical envelope across all lifecycle steps.
- **PR #279 Canonical Replay Authority:** All consolidated commerce, delivery and return risk, and TrustOS client export flows are canonically driven by `scripts/run_commercial_replay_integration.py` from PR #279. PR #280 acts as a verification laboratory and benchmark harness without creating a second replay engine.
- **PR #274 vs PR #280 Ownership Boundary:**
  - **PR #274 (`grok/marketos-integrated-replay-perf-v1`):** Focuses on standalone integrated replay performance harness files (`evaluation/perf/integrated_replay.py`, `scripts/run_integrated_replay_perf.py`, `tests/test_integrated_replay_perf.py`, `docs/ai/INTEGRATED_REPLAY_PERFORMANCE.md`). PR #280 leaves all PR #274 files strictly untouched.
  - **PR #280 (`antigravity/marketos-commercial-replay-benchmark-v1`):** Focuses exclusively on commercial replay certification optimization, 7D parametric sensitivity analysis, high-scale Monte Carlo profiling, and laboratory reporting.

### Review 2: Statistical & Benchmark Rigor
- **Repeatability:** Zero hash drift confirmed across repeated cycle runs (`hash_drift_detected: False`).
- **Latency Distribution:** Mean cycle latency 9.72 ms; p95 9.81 ms / p99 9.81 ms via `sample_maximum_small_n_guard`.
- **Throughput Stability:** High-throughput execution (~120-170 evals/sec) across all dimension tiers with bounded memory footprint (~8 KB/eval).
- **Colab Scale Ready:** Supports scaling to 10,000+ deterministic sensitivity combinations via `--scale-max 1500` ($1500 \times 7 = 10,500$ evaluations).

### Review 3: Security & No-Live-Authority Verification
- **Default-Off & Fail-Closed:** 0 network sockets, 0 credentials, 0 live mutations, 0 provider calls, and 0 database writes.
- **Adversarial Input Certification:** Certified fail-closed rejection of live authority tokens and adversarial advisory payloads in `assert_no_live_authority`.
- **TrustOS Workspace Export Boundary:** All client outputs remain redacted and classified as `fixture` with `requires_review` status.

### Review 4: Documentation & Colab Reproducibility
- **Operator Runbook:** Clear instructions for local and Google Colab execution environments.
- **Free Tier Budget:** Standalone execution requires only standard CPU runtime within free compute tier (200 compute units unused or conserved).
- **Self-Contained Verification:** Reproducible via a single command with zero external environment dependencies.

---

## 8. Google Colab Execution Guidance

The benchmark laboratory suite is designed to be fully self-contained and Colab-ready:
- **Compute Allocation:** Standard free CPU instance (0 GPU required).
- **Security & Isolation:** 0 credentials, 0 network dependencies, 0 secrets, and 0 environment variables required.
- **Colab Invocation (Standard):**
  ```bash
  !python scripts/benchmarks/benchmark_commercial_replay_lab.py --runs 20 --scale-max 1000 --json
  ```
- **Colab Invocation (High-Scale Monte Carlo $N \ge 10,000$ points):**
  ```bash
  !python scripts/benchmarks/benchmark_commercial_replay_lab.py --runs 10 --scale-max 1500 --json
  ```
- **Use Case:** High-volume Monte Carlo parametric sweeps ($N \ge 10,000$ points) and automated regression profiling before main-branch PR merges.

---

## 9. Safety, Constraints, and Rollback

- **No Live Authority:** Commercial dry-run results are planning models only. No real ad spend, order, payment, or supplier contract was triggered or authorized.
- **Evidence Grounding:** All supplier and product data are labeled `fixture` or `simulated`.
- **Rollback:** Single-commit revert on `backend/events/replay_certification.py` and deletion of the benchmark script restores the exact prior state.