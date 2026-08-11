# Phase 1 Evidence Benchmark Matrix

The benchmark matrix compares normalized candidate evidence across supplier proof, competitor proof, economics, assumptions, risk, and the expected value of the next validation. It reuses the Commerce Evaluation Framework and Phase 1 Readiness Cockpit; it does not run suppliers, extract competitors, write events, or promote products.

Each candidate receives an explicit decision: `advance_to_live_supplier_validation`, `advance_to_competitor_expansion`, `hold_for_credentials`, `reject_insufficient_margin`, `reject_insufficient_evidence`, `reject_high_risk`, `ready_for_readonly_deployment`, `needs_mapping_hardening`, or `needs_operator_review`.

Scores are deterministic. Supplier scoring rewards observed price, SKU, inventory, variants, shipping, and delivery. Competition scoring uses observed offers, pricing coverage, diversity, availability, and reviews. Economics combines those evidence qualities with margin and assumptions. Validation priority directs the highest-value next bounded proof; it never authorizes a live run.

## Commands

```powershell
python scripts/phase1_benchmark_matrix.py --json
python scripts/phase1_benchmark_matrix.py --candidate-seed tests/fixtures/benchmark_matrix/candidates.json --markdown
python scripts/phase1_benchmark_matrix.py --output artifacts/phase1_benchmark_matrix/latest --markdown
```

The default candidate set is synthetic fixture/demo evidence. It is intentionally marked `fixture_demo`, performs no network I/O, needs no credentials, and is not evidence of supplier availability, margin, demand, or launch readiness.

## Operator view

`GET /api/phase1/benchmark-matrix` is GET-only and uses only server-configured paths beneath `artifacts/`. The existing `/operator/events` page renders the top candidates, decision, validation priority, and evidence status without credential input or action buttons.

Use [Phase 1 Public Market Evidence Benchmark](PHASE1_PUBLIC_MARKET_BENCHMARK.md) to feed bounded multi-candidate public evidence into this same matrix without adding a second scoring engine.
