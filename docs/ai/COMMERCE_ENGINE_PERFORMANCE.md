# Commerce performance regression benchmark

Lane: `grok/marketos-commerce-engine-perf-v1` (PR #255)  
Base: `origin/main` `df59a0609897907c1565d7d5f78e20959095d430`  
Schema: `commerce-regression-benchmark-v2`  
Posture: fixture-only, no live providers, not a merge gate.

## What this lane is

A **regression-detecting measurement layer**. It times existing MarketOS
authorities when they import. It does not replace those authorities.

Two path classes are recorded separately and must not be mixed:

| Class | Meaning |
| --- | --- |
| `canonical` | `status=measured` only when the real module imported and ran |
| `sandbox_pattern_not_production` | indexed-vs-pairwise conflict scan inside `evaluation/perf/commerce_engine.py` |

Do **not** cite sandbox-pattern milliseconds as production MarketOS
performance.

## Canonical call graph (audit)

| Path | Authority | How measured | Typical status on main |
| --- | --- | --- | --- |
| supplier normalization | `evaluation.commerce.supplier_feasibility.build_report` | fixture `SupplierFeasibilityEvidence` rows | measured when checkout present |
| opportunity synthesis | `evaluation.commerce.opportunity_synthesis.build_product_opportunity_synthesis` | three fixture pillar packets | measured when checkout present |
| client-safe export | `evaluation.commerce.product_validation_report.generate` | explicit packets, no filesystem defaults | measured when checkout present |
| commerce-cycle packet | `backend.commerce.run_commerce_cycle` | dry-run attributed fixtures | often unavailable without backend extras |
| research-to-decision | `#247` | never reimplemented | unavailable on main |
| financial kernel | `backend.economics.kernel` (`#248`) | never driven | unavailable / not_run |
| competition combine | `backend.mvp_commerce.competition_intelligence.build_market_opportunity_report` | empty evidence combine | unavailable without mvp stack |
| competition fetch | `gather_market_intelligence` | **not called** | — |

Replay identity is SHA-256 of the serialized measured payload
(OpenLineage-style run identity, no vendor install).

## Benchmark matrix

Sizes: 100 / 500 / 1,500 / 5,000 (5,000 uses `max_rows` override; may
`not_run` if the payload is too large).

Stress: duplicate ids, conflicting offers, mixed currency, stale
evidence, malformed / secret-shaped rows, mixed evidence, replay
hashing, export projection.

Warmup: 1. Repeats: 5. Timer: `time.perf_counter`. Stats: mean / stdev /
min / max.

## Advisory budgets

Outcomes: `pass`, `regression`, `unavailable`, `not_run`, `malformed`.
Budgets are not a quality gate and do not block merge.

## Equivalence rules

For the sandbox pattern, pairwise and indexed detectors must agree and
replay hashes must match. Fixture evidence cannot become
`live_attestation`. Mixed currencies are listed, never converted.
Canonical adapters never mutate ranking or launch authority; they only
time existing functions.

## Commands

```powershell
python -m pytest -q tests/test_commerce_engine_perf.py tests/test_commerce_regression_benchmark.py
python scripts/run_commerce_engine_perf.py --mode all --size 200 --json
python -m compileall evaluation/perf scripts/run_commerce_engine_perf.py tests
```

## Public sources (not vendored)

| Source | License | Taken |
| --- | --- | --- |
| pytest-benchmark usage | MIT | warmup, min rounds, perf_counter, do not treat VM noise as truth |
| pyperf | PSF | report mean + variance, name the machine |
| OpenLineage 1.53.0 | Apache-2.0 | producer / job / run hash |
| OpenTelemetry | Apache-2.0 | span-like path_id names; no exporter |
| DuckDB / Polars / dlt | MIT / MIT / Apache-2.0 | reviewed; not imported |

## Grok / CoderOS / gstack tools

Used: GitHub connector, web search, code execution, CoderOS skill
read-only. Not present in this runtime: gstack-benchmark,
gstack-plan-eng-review, gstack-review, gstack-qa, ECC/Hermes plugins,
CoderOS CLI probe (CoderOS source is frozen).

## Rollback

Remove exclusive files under `evaluation/perf`, the two scripts/tests,
and this doc; or close draft PR #255. No schema migration.
