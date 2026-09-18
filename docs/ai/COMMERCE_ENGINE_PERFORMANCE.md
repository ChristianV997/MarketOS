# Commercial-engine performance and reliability

Lane: `grok/marketos-commerce-engine-perf-v1`
Base: `origin/main` `df59a0609897907c1565d7d5f78e20959095d430`
Posture: fixture-only, no live providers, no merge.

## Why this exists

`scripts/benchmark_commerce_cycle.py` times the canonical commerce loop when
`backend.commerce` imports. `#249` `scripts/run_high_value_path_harness.py`
classifies missing modules. Neither measures bounded offer normalization,
duplicate/conflict detection, mixed-currency isolation, or replay equality
under stress.

This lane adds that measurement seam and a measured reliability fix:
pairwise conflict scans become an indexed identity map with equivalent
output.

## Classification (verified by COMMERCIAL-REPLAY-INTEGRATION-V3)

**Benchmark-only harness, not a wired optimization of any canonical
production path.** `evaluation/perf/commerce_engine.py` is fully
self-contained: it generates its own fixture rows (`build_rows()`), parses
its own money/currency/evidence-state fields from scratch, and detects
conflicts over its own `ProcessResult` records. It never imports or calls
`evaluation.commerce.opportunity_synthesis`, `evaluation.commerce.supplier_feasibility`,
`backend.economics.kernel`, or any other canonical scoring/economics/report
authority (confirmed by this module's own `authorities_not_replaced` field
in every harness run). No production code path was changed or sped up by
this PR -- the "before/after" comparison is entirely between two algorithms
written inside this same new module.

It is preserved because it demonstrates a real, reusable pattern
(identity-map conflict detection vs. a pairwise scan) with genuine measured
evidence, in case a similar O(n^2) conflict scan is ever found in a
canonical module and needs the same fix applied *there*. This PR does not
apply that fix anywhere outside its own sandbox.

### Measured at 10 / 100 / 1,000 rows (`many_candidates` fixture, 5 repeats, this sandbox, Python 3.11.15)

| Rows | Pairwise mean (ms) | Indexed mean (ms) | Output equivalent | Replay stable (both) |
| --- | --- | --- | --- | --- |
| 10 | 0.036 | 0.034 | true | true |
| 100 | 0.417 | 0.312 | true | true |
| 1,000 | 11.609 | 3.229 | true | true |

The advantage is negligible at 10 rows, modest at 100, and clear (~3.6x) at
1,000 -- consistent with the pairwise scan's O(n^2) growth against the
indexed scan's O(n), and reproduced independently of the PR's own
1,500-row headline figure (22.88ms -> 4.624ms, also reproduced unchanged).

## Exclusive files

- `evaluation/perf/commerce_engine.py`
- `evaluation/perf/__init__.py`
- `scripts/run_commerce_engine_perf.py`
- `tests/test_commerce_engine_perf.py`
- `docs/ai/COMMERCE_ENGINE_PERFORMANCE.md`

Do not edit `#247` research-to-decision, `#248`/`#250` economics kernel,
`#249` deploy harness, synthesis scoring, or event stores.

## Commands

```powershell
python -m pytest -q tests/test_commerce_engine_perf.py
python scripts/run_commerce_engine_perf.py --size 200
python -m compileall evaluation/perf scripts/run_commerce_engine_perf.py tests/test_commerce_engine_perf.py
```

## Recorded fields

scenario, input size, row count, wall time, repeated-run equality, output
size, failure classification, environment, commit SHA, evidence state.

## Public sources reviewed (not vendored)

| Source | License | Use |
| --- | --- | --- |
| Python `time.perf_counter` / `hashlib` | PSF | timing + replay |
| pytest | MIT | focused tests |
| Hypothesis docs | MPL-2.0 | case shapes only |
| OpenLineage spec 1.53.0 | Apache-2.0 | producer/job/replay identity |
| OpenTelemetry Python | Apache-2.0 | no exporter added |
| DuckDB / Polars / dlt | MIT / MIT / Apache-2.0 | deferred; row counts stay in stdlib |

## Safety

Sanitized fixtures only. Secret-shaped keys are rejected. Fixture evidence
cannot become `live_attestation`. Mixed currencies are listed, never FX'd.
No second scorer.

## Rollback

Delete the five exclusive files / close the draft PR. No schema migration.
