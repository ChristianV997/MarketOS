# High-Leverage Backlog

Current maturity: Phase 1 architecture is implemented and fixture-tested;
authenticated CJ evidence awaits an operator-owned credentialed proof.

1. Run `scripts/phase1_readiness_report.py --json` and follow its single next action.
2. If it reports `credential_missing`, complete server-side CJ setup and run one operator-approved CJ read-only validation.
3. Record observed result or payload/account limitation.
4. Improve CI lane selection only after its measured use on several PRs.
5. Expand the evidence benchmark matrix after CJ outcome is known.
6. Prove the read-only deployment stack before discussing mutation authority.

`impact_planner.py` ranks this static backlog without GitHub/network access and can accept a sanitized readiness report with `--readiness-report`.

Use `scripts/phase1_benchmark_matrix.py --json` to choose which candidate has the highest evidence-backed validation value; fixture ranking is not live proof.
