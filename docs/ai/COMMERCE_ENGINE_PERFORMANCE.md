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
