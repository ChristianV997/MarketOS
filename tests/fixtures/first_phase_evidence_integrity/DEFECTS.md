# First-phase evidence defects recorded by PR #227

These are product defects. Do not patch them in this test-only PR.

## SYN-GRADE-LIVE-LABEL
- File: `evaluation/commerce/opportunity_synthesis.py` (`_grade`)
- Owner lane: opportunity-synthesis / commerce foundation
- Severity: P1
- Reproduction: three pillar reports where any item uses `evidence_mode=live_readonly`
- Observed: `confidence_grade == A_live_validated`
- Expected: fixture or unlabeled local input cannot claim live authorization

## VAL-GENERATE-DEFAULT-BUILDERS
- File: `evaluation/commerce/product_validation_report.py` (`generate`)
- Owner lane: product-validation
- Severity: P1
- Reproduction: `generate()` with no benchmark/readiness/deployment stubs
- Observed: calls `build_benchmark_from_paths` / `build_from_paths` / `build_readiness`; next action can mention CJ credentials
- Expected: omit path builders unless an explicit fixture/path is supplied

## SYN-ALIAS-NO-COLLAPSE
- File: `evaluation/commerce/opportunity_synthesis.py` (`_candidate_map`)
- Owner lane: opportunity-synthesis
- Severity: P2
- Reproduction: two marketplace candidates sharing `query` and `source_family` but different `candidate_id`
- Observed: `candidate_count == 2`
- Expected: correlated aliases should not double-count the same source family

## RUN-228-ACTUAL-ON-FIXTURE
- File: `scripts/operators/run_first_phase_intelligence.ps1` (`Get-StageClassification`)
- Owner lane: Windows operator / PR #228
- Severity: P1 evidence-truth
- Reproduction: default fixture-demo run exits 0
- Observed: summary `overall_classification` and stage classifications are `actual`
- Expected: fixture/simulated/manual_import must not be labeled `actual`
