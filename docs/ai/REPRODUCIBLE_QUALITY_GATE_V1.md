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

Run the workflow-compatible local preflight when final CI evidence does not
yet exist:

```powershell
python scripts/ai/run_local_quality_gate.py --from-git --execute --phase preflight --generated-at 2026-08-29T12:00:00+00:00 --json
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

The status vocabulary is stable and included in the report as
`status_taxonomy`: `passed`, `failed`, `unavailable`, `timed_out`, `not_run`,
`not_configured`, `collection_failed`, `blocked`, `malformed`, and
`ci_unavailable`. Pytest
collection errors are detected separately from test failures. A collection
error with a missing-import marker is classified as `unavailable_dependency`;
other collection errors are `collection_failed`. A malformed security scanner
result is `malformed`; a non-zero scanner result with valid output is
`security_scanner_failure` unless findings are present, in which case it is
`security_finding`. Failed whitespace validation is `diff_failure`. Timeouts
retain status `timed_out` and never become passes.

An operator-supplied baseline may classify a current failure as
`pre_existing_failure`. A current failure with changed paths and a passing
baseline is `changed_scope_failure`. If the baseline does not prove either
origin, the result is `failure_origin_unverified`; the gate does not infer
ownership from history or from a green-looking summary.

CI is an explicit input only. The local gate never queries GitHub. A missing
CI input is `ci_unavailable`, and a reported CI failure with zero executed
steps is also `ci_unavailable`, not a pass. A real failure with executed steps
is a failure. For local replay of sanitized CI metadata, use
`--ci-evidence-file <path>` with schema `MarketOS.CIEvidence.v1`. The file
contains only run status/conclusion and job metadata; raw logs and unknown
fields are rejected. Required jobs pass only when a runner is assigned, at
least one step executed, logs are available, the job completed successfully,
and its required check status is `success`. Otherwise the evidence remains
`ci_unavailable` or `failed`. The file is bounded to 64 KiB and 100 jobs.

```json
{
  "schema": "MarketOS.CIEvidence.v1",
  "run": {"status": "completed", "conclusion": "failure"},
  "required_jobs": ["agentic-quality-gate"],
  "jobs": [{
    "name": "agentic-quality-gate",
    "required": true,
    "status": "completed",
    "conclusion": "failure",
    "runner_id": 0,
    "runner_name": "",
    "steps_executed": 0,
    "logs_available": false,
    "required_check_status": "failure"
  }]
}
```

## Readiness and exits

The machine-readable report is schema `MarketOS.LocalQualityGate.v2`. The
process exits are:

| Exit | Stable meaning |
|---:|---|
| `0` | all observed checks passed; inspect readiness separately |
| `1` | observed failure, collection failure, security finding/scanner failure, diff failure, timeout, blocked safety state, or unverified failure |
| `2` | missing tool/dependency, checks not run, or unavailable CI |
| `3` | malformed request, baseline, or repository configuration |

`ready_for_supervised_use` is true only for an executed report with passed
checks, clean git state, and observed CI success with at least one executed
step. Human review remains required. Planning output never authorizes
deployment, publishing, provider calls, supplier calls, commerce mutation,
repair, merge, or credential use.

Preflight has a deliberately narrower check scope and exit contract: it runs
only compile, the quality-gate regression tests, focused Ruff checks, and the
diff check. Full repository tests and security/container jobs remain separate
CI evidence. It exits zero only when its local checks pass, but it always
reports `ready_for_supervised_use: false` and does not turn missing final CI evidence into success. Supply complete
sanitized `MarketOS.CIEvidence.v1` to the default final phase after required
jobs finish to obtain final attestation. If a local check fails before that
evidence exists, its failure classification remains visible instead of being
replaced by `ci_unavailable`.

## Operator interpretation

1. Treat `configuration_error`, `failed`, and `unavailable` as blockers.
2. Use the `classification` and per-check `failure_origin` as evidence, not
   as permission to ignore a failure.
3. Resolve missing dependencies outside the gate, then rerun with the same
   injected timestamp policy.
4. Keep baseline reports operator-supplied and reviewable; never fabricate a
   baseline to convert a failure into a pass.
5. Retain only the structured report needed for handoff, not command logs.
