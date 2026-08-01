# Performance Baseline

Updated: 2026-08-01

This document records deterministic local benchmarks. It is not a production-capacity claim.

## Commands

```bash
python scripts/benchmark_inference_stack.py --runs 50 --json
python scripts/benchmark_commerce_cycle.py --runs 20
```

The inference benchmark forces the mock provider, makes no network requests, and measures routing, completion, cache growth, and peak traced memory. The commerce benchmark already forces the mock chain and measures the canonical dry-run feedback path.

## Ownership and thresholds

- Codex owns benchmark scripts, benchmark tests, and performance workflow changes.
- The existing commerce-cycle p95 limit remains the CI authority.
- Inference results are diagnostic until a stable baseline is recorded in CI.
- An optimization requires measured improvement or a verified allocation/failure reduction; do not optimize from intuition alone.
