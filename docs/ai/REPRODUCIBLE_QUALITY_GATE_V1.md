# Reproducible Quality Gate v1

This document defines the offline-first local quality-gate procedure for
MarketOS. The implementation is the existing
`scripts/ai/run_local_quality_gate.py`; this document describes its
deterministic reporting contract rather than creating another gate.

## Invocation

Plan the checks without executing them:

```powershell
python scripts/ai/run_local_quality_gate.py --from-git --generated-at 2026-08-29T12:00:00+00:00 --json
```

Run the fixed local checks in a clean isolated worktree:

```powershell
python scripts/ai/run_local_quality_gate.py --from-git --execute --generated-at 2026-08-29T12:00:00+00:00 --json
```

The timestamp is injected by the operator. Check ordering is stable and is
always `compile`, `pytest`, `ruff`, `typed`, `frontend`, `security`, then
`diff_check`. The executable mode does not install dependencies or make
network/provider calls. An absent `node_modules` directory is reported as
`unavailable_dependency`; it is not repaired by the gate.

## Evidence contract

Each executed check records only its name, redacted command shape, tool
availability, execution state, exit-derived status, bounded numeric summary,
and a classification. Raw stdout, stderr, environment values, transcripts,
and credentials are never included in the report. Semgrep findings are
counted from structured output, while non-empty findings remain visible even
when the scanner exits zero.

An operator-supplied baseline may classify a current failure as
`pre_existing_failure`. A current failure with changed paths and a passing
baseline is `changed_scope_failure`. If the baseline does not prove either
origin, the result is `failure_origin_unverified`; the gate does not infer
ownership from history or from a green-looking summary.

CI is an explicit input only. The local gate never queries GitHub. A missing
CI input is `ci_unavailable`, and a reported CI failure with zero executed
steps is also `ci_unavailable`, not a pass. A real failure with executed steps
is a failure.

## Readiness and exits

The machine-readable report is schema `MarketOS.LocalQualityGate.v2`. The
process exits are:

| Exit | Stable meaning |
|---:|---|
| `0` | dry-run or all observed checks passed; inspect readiness separately |
| `1` | observed failure, security finding, timeout, blocked safety state, or unverified failure |
| `2` | missing tool/dependency or unavailable CI |
| `3` | malformed request, baseline, or repository configuration |

`ready_for_supervised_use` is true only for an executed report with passed
checks, clean git state, and observed CI success with at least one executed
step. Human review remains required. Planning output never authorizes
deployment, publishing, provider calls, supplier calls, commerce mutation,
repair, merge, or credential use.

## Operator interpretation

1. Treat `configuration_error`, `failed`, and `unavailable` as blockers.
2. Use the `classification` and per-check `failure_origin` as evidence, not
   as permission to ignore a failure.
3. Resolve missing dependencies outside the gate, then rerun with the same
   injected timestamp policy.
4. Keep baseline reports operator-supplied and reviewable; never fabricate a
   baseline to convert a failure into a pass.
5. Retain only the structured report needed for handoff, not command logs.
