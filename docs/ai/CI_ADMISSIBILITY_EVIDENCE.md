# CI Admissibility Evidence

## Purpose

`ci_admissibility_probe.py` is a bounded, read-only classifier for sanitized
GitHub Actions metadata. It explains whether evidence demonstrates execution,
is still pending, is unavailable, or represents a real executed failure. It
does not call GitHub, fetch logs, read credentials, authorize merge, authorize
deployment, or replace the existing local quality gate and PR-readiness
authorities.

The canonical local quality authority remains:

- `scripts/ai/run_local_quality_gate.py`;
- `scripts/ai/pr_readiness_report.py`;
- the repository's existing workflows and merger review.

The diagnostic is deliberately a consumer-friendly projection. It accepts the
existing `MarketOS.CIEvidence.v1` contract and the richer sanitized
`MarketOS.CIAdmissibilityEvidence.v1` adapter contract. It does not change the
canonical CIEvidence loader.

## Operator Commands

From an isolated MarketOS worktree:

```powershell
python scripts/ai/ci_admissibility_probe.py --input .\ci-evidence.json --json
python scripts/ai/ci_admissibility_probe.py --input .\ci-evidence.json --markdown
python scripts/ai/ci_admissibility_probe.py --json
```

The command performs only a bounded local file read. It never invokes `gh` or
any external provider. Exit codes are evidence-only process signals:

- `0`: all required CI evidence executed and passed;
- `1`: an executed failure or timeout was observed;
- `2`: pending, unavailable, zero-step, runnerless, missing, or no evidence;
- `3`: malformed, unsafe, oversized, or unsupported input.

These codes do not authorize merge or deployment. Unexpected process errors are
not converted into a successful report.

## Input Contract

The richer adapter contract is:

```json
{
  "schema": "MarketOS.CIAdmissibilityEvidence.v1",
  "repository": "ChristianV997/MarketOS",
  "candidate_head_sha": "<40 hex characters>",
  "target_head_sha": "<same candidate SHA>",
  "target_base_sha": "<base SHA>",
  "workflow": {
    "name": "CI",
    "run_id": 42,
    "status": "completed",
    "conclusion": "success",
    "head_sha": "<same candidate SHA>",
    "base_sha": "<base SHA>",
    "created_at": "2026-09-22T08:00:00+00:00",
    "updated_at": "2026-09-22T08:05:00+00:00"
  },
  "required_policy": {
    "source": "repository_policy",
    "revision": "ci-policy-v1",
    "jobs": ["test"],
    "fingerprint": "<sha256 of canonical {jobs, revision} object>"
  },
  "required_jobs": ["test"],
  "jobs": [
    {
      "name": "test",
      "required": true,
      "status": "completed",
      "conclusion": "success",
      "head_sha": "<same candidate SHA>",
      "run_id": 42,
      "workflow_name": "CI",
      "runner_id": 101,
      "steps_executed": 4,
      "log_status": "available",
      "log_http_status": 200,
      "required_check_status": "success"
    }
  ],
  "checks": []
}
```

Only sanitized metadata is accepted. Raw logs, stdout/stderr, credentials,
environment values, arbitrary payloads, comments, and private notes are
rejected. Inputs are capped at 64 KiB, 100 jobs, 100 checks, 200 step names
per job, and 64 nested JSON containers. Input files must be regular files
inside the selected worktree.

`log_status` is metadata, not a log payload:

- `available` with a successful executed job can support `pass`;
- `missing`, `not_found`, `forbidden`, or `unavailable` cannot support a
  successful job;
- an executed failure remains `executed_failure` even when its logs are
  unavailable, so missing logs never hide a real failure.

The existing `MarketOS.CIEvidence.v1` shape is accepted for compatibility. It
does not contain candidate/workflow identity fields, so it remains visible as
`missing_workflow_context` and cannot admit a pass by itself.

## Classification Matrix

| Evidence | Job classification | Overall result |
|---|---|---|
| runner ID `0`/absent or zero steps | `zero_step_runnerless` | `ci_unavailable` |
| positive steps, runner, failure conclusion | `executed_failure` | `executed_failure` |
| positive steps, runner, timeout conclusion | `timed_out` | `timed_out` |
| queued/in-progress/pending job | `pending` | `pending` |
| successful execution without retrievable logs | `unavailable_logs` | `ci_unavailable` |
| successful execution with bound workflow/head/log evidence | `pass` | `pass` |
| job/head/run/workflow mismatch | `stale_metadata` | `ci_unavailable` |
| missing workflow identity | `missing_workflow_context` | `ci_unavailable` |
| workflow was never created | `workflow_never_created` | `ci_unavailable` |
| candidate/target/workflow head or base mismatch | `stale_worktree_metadata` | `ci_unavailable` |
| absent required job | `required_job_missing` | `ci_unavailable` |
| malformed or contradictory metadata | `malformed` | `malformed` |
| deploy-preview or Netlify check | `not_ci` | excluded from CI result |

An overall `pass` requires every required job to execute successfully, have
retrievable log metadata, and match the candidate workflow identity. A
workflow-level failure with no executed steps does not prove a code failure;
the result remains `ci_unavailable`. Mixed evidence preserves per-job states
and gives executed failures priority over incomplete evidence only when an
actual executed failure exists.

Rich adapter input must include a repository-sourced `required_policy` envelope,
its deterministic fingerprint, the candidate head, and the target head/base
binding. The fingerprint proves that the declared policy fields were not
changed after collection; `provenance: declared_sanitized` remains an input
claim and is not authentication. A caller cannot opt into the canonical
compatibility mode with a boolean or omit these bindings. The compatibility
`MarketOS.CIEvidence.v1` input remains intentionally incomplete for workflow
identity and therefore cannot admit a pass by itself.

## Output and Redaction

JSON is sorted and fingerprinted with SHA-256 over the deterministic report.
Markdown uses escaped table fields and is capped at 120,000 characters. URLs
with credentials, sensitive query parameters, or fragments become
`[redacted-url]`; raw credential values are never echoed. No wall-clock time is
generated by the probe; reports use `generated_at: "deterministic"`.

The output explicitly includes:

- `admissible_evidence`, which is evidence quality only;
- `authority.merge_authorized: false`;
- `authority.deployment_authorized: false`;
- `authority.intended_consumers`, pointing to the existing quality/readiness
  surfaces; `integrated_consumers` remains empty because this classifier does
  not silently replace or mutate those authorities;
- `authority.external_actions_authorized: false`;
- one bounded operator action and all blockers.

Neither `admissible_evidence` nor a `pass` classification authorizes a merge,
deployment, provider call, order, payment, publishing action, or customer
communication.

## Safety and Rollback

The probe performs no network calls, GitHub API calls, credential reads,
provider calls, uploads, worktree writes, or database mutations. It is safe to
run against fixture files and sanitized operator exports. Rollback is a normal
revert of the focused implementation commit; do not reset or delete a shared
worktree.
