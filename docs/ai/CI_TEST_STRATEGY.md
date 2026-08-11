# CI and Test Throughput Strategy

The current CI remains authoritative. This document proposes additive lanes;
`scripts/ai/ci_matrix_plan.py` only recommends them and does not alter Actions.

| Lane | Trigger | Minimum work |
|---|---|---|
| docs-only | docs/instructions only | diff check, session finish |
| python compile | all Python changes | compileall |
| architecture | backend/contracts/events | architecture boundaries |
| supplier/evidence | CJ/evidence/Commerce MVP | adapter, harness, evaluation |
| evaluation | `evaluation/commerce` | evaluation + architecture |
| frontend | `frontend/` | TypeScript/Vite build |
| security | all PRs | Semgrep policy |
| live-readonly manual | operator-approved credential window | one bounded probe, never CI |
| nightly full | scheduled/manual | complete pytest suite |

Collect lane timing before changing workflows. Avoid broad GitHub Actions
rewrites until the measured bottleneck warrants one.

The advisory `Agentic Quality Gate` workflow validates the scripts themselves,
prints the selected lanes, and writes the local quality-gate report to the PR
job summary. It is intentionally not a required check until its false-positive
rate is measured across normal PRs.
