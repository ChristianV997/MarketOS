# Commercial replay laboratory certification (#280)

Lane: `grokchat-commercial-replay-laboratory-certifier-v2`  
PR: [#280](https://github.com/ChristianV997/MarketOS/pull/280) `antigravity/marketos-commercial-replay-benchmark-v1`  
Schema: `commercial-replay-lab-benchmark-v2`  
Status: draft, do not merge

## Ownership (refreshed this session)

| PR | Role | Branch | HEAD |
| --- | --- | --- | --- |
| #274 | conformance / Event-path arbitration | `grok/marketos-integrated-replay-performance-v1` | `f51b746fad033a68d9c332c19784e9b2f045c9ce` |
| #279 | canonical replay CLI | `codex/marketos-commercial-replay-consolidation-v1` | `54aaa1a2773dc914e64fe6b0284f52134e184b55` |
| #280 | laboratory | `antigravity/marketos-commercial-replay-benchmark-v1` | previous `4565cca1212c5cce143680d246ba33032bd41362` |
| main | base | `main` | `e6a2e88e03ed07e4da8f6351aa114f5d5a8007c6` |

#274 and #279 files were not edited.

## Execution class

`source_certified_plus_github_blob` — **not** a real authenticated MarketOS worktree.

This sandbox cannot `git clone` `ChristianV997/MarketOS` (`could not read Username for 'https://github.com'`).  
`grok` CLI, Hermes, ECC skills, and CoderOS probe are not installed.

A sparse blob tree is **not** equivalent evidence to Phase 1. Do not treat prior sandbox walls as newly measured #280 numbers.

## 17 versus 37 (from executable code, asserted independently)

```
commerce: builder() -> run_dry_run_lifecycle -> lifecycle_events
  1 commerce_dry_run_started
  + 15 LIFECYCLE_STEPS
  + 1 commerce_dry_run_completed
  = 17
  owner: main + #274 harness + #280 lab

#279 CLI _replay_scenario only:
  those 17
  + run_fulfillment_risk_dry_run(customer_return_merchant_paid).events  # 20
  = tuple((*commerce_events, *fulfillment_events))  # 37
```

The lab measures 17. Comparing 17-event walls or hashes to 37-event rows is invalid.

## Defects found in #280 @ 4565cca1

1. `run_canonical_replay_integration()` certified `all_invariants_satisfied=True` on `ImportError`. Tests required that. Unavailable #279 is not a pass.
2. On the main/#280 CLI (commerce-only), governor / ledger / TrustOS invariants were default-True without observing those fields.
3. Records stored only the **terminal** `Event.replay_hash`, not the 17-hash sequence or the aggregate SHA-256 of that sequence. Report claimed aggregate-hash certification without computing it.
4. Statistical drift compared only terminal hashes.
5. `evidence_classification` was hardcoded `"fixture"` while four builders use `evidence_state="observed"` and solar uses `"fixture"`. Observed is not live and must not be rewritten to fixture or to `live_readonly`.
6. Missing negative controls for wrong event count, synthetic field-hash identity, invalid sample shape, truncated symbols, evidence escalation.
7. `p95`/`p99` with n=3–5 equal max(sample). Reportable, not an independent tail.

## Production file

`backend/events/replay_certification.py` on #280 moves `json.dumps` inside the `aggregate_type=="advisory"` branch.

Main already token-scans **only** advisory events; the extra dumps on non-advisory events did not change violation lists. `Event.replay_hash` is `sha256(canonical_json())` and was not changed.

No further production optimization in this session. The existing three-line patch is left in place (semantically equivalent). Revert it if the operator wants #280 file-disjoint from production certification.

## Fixes in this certifier commit (lab + tests + this note only)

- Record full `Event.replay_hash` sequences, event IDs, and aggregate hash.
- Refuse to measure a non-17 commerce trail in `run_scenarios`.
- Unavailable or commerce-only CLI cannot claim the 13-point #279 set.
- Drift uses aggregate sequence hashes.
- Evidence classification follows builder `evidence_state`.
- Adversarial lab tests added.
- Field-hash remains a named negative control.

## Historical published 17-event aggregate hashes (#274 actual path)

These are **not** re-measured here. They remain the last claimed Event-path aggregates:

| Scenario | Evidence | Events | Aggregate `Event.replay_hash` |
| --- | --- | ---: | --- |
| hydroponics_positive_candidate | observed | 17 | `6fb5335152136dd144dce4f9409c9556b73586e2000909d341642b322e448043` |
| smart_pet_support_burden_candidate | observed | 17 | `454324ce4704c1e2c962c966e72a93f3bdc21179cd55db2f8d65441b772095ac` |
| solar_4g_security_blocked_candidate | fixture | 17 | `44ea844bac5e4822416ca71cb9ebf59af8b3c46b4a1ceb01a56a86cae538f3e9` |
| commodity_electronics_rejected_candidate | observed | 17 | `b19c522f0ecc954a268a7369634f1013f49f2b9f2387250fc396805416131aa4` |
| high_ticket_deferred_candidate | observed | 17 | `f9d709c9366b35985f15cbf0018e741a530f5250567a335a7407d471d37c13fe` |

#280 report terminal hashes at 4565cca1 are a different object (last event only) and must not be compared to these aggregates.

## Methodology the lab now records

- Commit / env: caller must stamp from a real worktree (`git rev-parse HEAD`, Python version).
- Warm-up: `StatisticalComparisonLaboratory` discards `warmup_cycles` before timing.
- Timer: `time.perf_counter`.
- Identity: per-event `Event.replay_hash` + aggregate SHA-256 of concatenation.
- Memory: `tracemalloc` in the scaling helper only (kernel sweep, not Event path).
- Secrets / raw provider payloads: lab serializes `DryRunLifecycleReport.to_dict()` only.
- Live actions: fixture builders set `live_actions_taken=False`; attestation cannot upgrade fixture/observed to live.

## Checks

| Check | Result |
| --- | --- |
| Source review of #274/#279/#280 heads | done |
| `python -m compileall` on patched lab/tests | syntax parsed in sandbox |
| pytest #280 / #279 / #274 / architecture | **unrun** (no checkout) |
| Ruff / session_finish / diff check | **unrun** |
| GitHub CI | `ci_unavailable` historically; not re-run |
| grok / Hermes / ECC / CoderOS | unavailable |
| Merge | not performed |

## Safety

No providers, credentials, customer data, orders, payments, refunds, ads, messages, deployment, or live network mutations.

## Rollback

Revert the certifier commit on `antigravity/marketos-commercial-replay-benchmark-v1` or close draft #280. Base remains `e6a2e88e`.

## Operator next action

On a machine that can clone the private repo:

```
git fetch origin --prune
git worktree add /tmp/wt-280 origin/antigravity/marketos-commercial-replay-benchmark-v1
cd /tmp/wt-280
python -m pytest -q tests/benchmarks/test_commercial_replay_lab.py \
  tests/system/test_commercial_dry_run_replay_integration.py \
  tests/system/test_public_signal_replay_certification.py
python scripts/benchmarks/benchmark_commercial_replay_lab.py --json
# read-only #279 / #274 worktrees for 37-event and conformance suites
```

Do not merge.
