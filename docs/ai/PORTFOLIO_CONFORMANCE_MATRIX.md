# Portfolio Conformance Matrix

The portfolio conformance matrix is a bounded, read-only operator view of the
open MarketOS PR queue. It combines sanitized PR metadata with local Git
identity and consumes the existing quality/readiness authorities. It does not
replace `scripts/ai/run_local_quality_gate.py`,
`scripts/ai/pr_readiness_report.py`, GitHub Actions, or the Merger Agent.

Schema: `MarketOS.PortfolioConformanceMatrix.v1`

## Purpose

The matrix answers one narrow operator question:

> Which open PRs can be evaluated next, what evidence is missing, and what
> ownership or ancestry conflict must be resolved before an existing merger
> authority can act?

It reports, without making a merge decision:

- the refreshed local `origin/main` SHA;
- each sanitized PR base SHA, head SHA, and merge-base SHA;
- changed-file collisions and canonical-authority overlaps;
- stacked dependency head status, including merged dependencies;
- CI evidence classifications for required jobs;
- local evidence classes without upgrading fixture or simulated evidence;
- deterministic topological merge order where dependencies permit one;
- blockers and one stable next action;
- a SHA-256 fingerprint over the normalized report.

`merge_authorized` is always `false`. The existing PR-readiness and merger
authorities remain the only release decision path.

## Commands

From an isolated MarketOS worktree:

```powershell
git fetch origin --prune
python scripts/ai/portfolio_conformance_matrix.py --json
python scripts/ai/portfolio_conformance_matrix.py --input .\portfolio-metadata.json --json
python scripts/ai/portfolio_conformance_matrix.py --input .\portfolio-metadata.json --markdown
```

Without `--input`, the command reports local Git identity and explicitly
classifies the portfolio input as unavailable. It does not call GitHub and does
not infer an empty queue as a clean portfolio.

The `--input` file is an operator- or integration-owned sanitized adapter
output. The matrix never invokes `gh`, GitHub APIs, providers, credentials, or
network services. A live adapter may collect public PR metadata separately,
normalize it to the contract below, and pass the file to this command.

The command exits zero when it successfully renders a matrix, including a
blocked matrix. Malformed input renders a bounded `portfolio_status:
malformed` report and exits `2`; it never becomes a pass. The report status and
blockers are the evidence; this command is not a second merge gate.

## Sanitized Input Contract

The adapter root is:

```json
{
  "schema": "MarketOS.PortfolioConformanceInput.v1",
  "repository": "ChristianV997/MarketOS",
  "origin_main": "<40 hexadecimal characters>",
  "workspace_id": "optional-canonical-workspace",
  "client_id": "optional-canonical-client",
  "pull_requests": []
}
```

Each pull request may contain only:

```json
{
  "number": 299,
  "title": "sanitized public title",
  "state": "open",
  "is_draft": true,
  "base_ref": "main",
  "base_sha": "<sha>",
  "head_ref": "codex/example",
  "head_sha": "<sha>",
  "merge_base_sha": "<sha>",
  "workspace_id": "optional-canonical-workspace",
  "candidate_id": "optional-candidate-id",
  "client_id": "optional-canonical-client",
  "economics": {
    "gross_margin": 0.0,
    "currency": "USD",
    "evidence_state": "simulated"
  },
  "changed_files": ["scripts/example.py"],
  "depends_on": [
    {"number": 290, "head_sha": "<sha>", "available": true}
  ],
  "required_checks": ["test"],
  "required_checks_source": "branch_protection_adapter",
  "ci_jobs": [
    {
      "name": "test",
      "workflow_name": "Agentic Quality Gate",
      "kind": "ci",
      "status": "completed",
      "conclusion": "success",
      "required": true,
      "head_sha": "<same PR head SHA>",
      "runner_id": 123,
      "steps_executed": 4,
      "logs_available": true
    }
  ],
  "local_evidence": {
    "classification": "actual_executed",
    "status": "passed",
    "fingerprint": "<optional sha>"
  },
  "authority_claims": ["quality_gate"]
}
```

`required_checks_source` must be `branch_protection_adapter`; this is a
provenance contract for the sanitized adapter and is not a merge authorization
or a substitute for reviewing the source adapter. Every CI job must carry the
exact PR `head_sha`, so evidence cannot be reused across heads.

Deploy preview markers (`netlify`, `deploy-preview`, `deploy_preview`,
`preview-deploy`) are strictly forbidden in `required_checks` and fail closed.
Jobs carrying these markers or declaring `kind: "deploy_preview"` cannot be
marked required, are segregated into `non_ci_checks`, and never satisfy CI
requirements or promote CI status to `pass`. In-progress jobs cannot claim
final logs are available.

Portfolio rows must belong to a single workspace and client; conflicting
`workspace_id` or `client_id` values fail closed. When provided, `economics`
explicit-zero values (`gross_margin: 0.0`) are preserved as `explicit_zero`
distinct from absent/omitted economics (`missing`).

The adapter must not include PR bodies, comments, private notes, raw logs,
provider payloads, credentials, tokens, output dumps, or arbitrary fields. The
matrix rejects unknown fields, secret-shaped values, unsafe paths, duplicate
PRs, duplicate jobs, required-flag mismatches, oversized input, and malformed
SHA/path values. It retains only normalized metadata and never echoes rejected
input values.

Bounds are 64 KiB per input file, 50 PRs, 250 changed files per PR, 200 CI jobs
per PR, and 200 step names per job. The Markdown renderer is capped at 120,000
characters.

## CI Classification

The matrix evaluates required jobs independently before deriving the PR-level
classification.

| Evidence | Classification | Meaning |
|---|---|---|
| completed, successful, runner ID greater than zero, steps greater than zero, logs available | `pass` | Executed and inspectable required job |
| completed failure with a runner and executed steps | `executed_failure` | Real CI failure; never unavailable |
| timeout with a runner and executed steps | `timed_out` | Timeout remains a timeout |
| queued, pending, waiting, or in progress | `pending` | No final result yet |
| zero steps, runner ID zero, or missing runner | `zero_step_runnerless` | No admissible execution; PR result becomes `ci_unavailable` |
| successful completion without logs | `unavailable_logs` | Cannot certify the success |
| required check absent from the job set | `ci_unavailable` | Required evidence is missing |
| unknown state/conclusion or inconsistent step metadata | `malformed` | Fail closed |

An executed failure has priority over incomplete evidence when both are present;
the report retains both per-job classifications. A zero-step job with a
failure conclusion is still `zero_step_runnerless`, never `executed_failure`.
No run-level success, Netlify status, local fixture, or empty job list can
substitute for executed required CI evidence. Deploy preview and Netlify entries
are segregated to `non_ci_checks` and do not contribute to CI admissibility.

## Ancestry, Stacking, and Dependencies

For a PR based on `main`, aligned ancestry requires:

1. `base_sha` equals the injected current `origin_main`;
2. `merge_base_sha` equals `base_sha`;
3. the PR head and base values are valid SHA strings.

For a stacked PR, `base_ref` must be accompanied by a dependency whose supplied
head matches the dependency PR in the same matrix. A dependency can be
`dependency_satisfied` or `merged_dependency_satisfied`. Missing, unavailable,
or stale dependency heads block the proposed order. A stacked base SHA that
does not match its declared dependency is `stacked_base_sha_mismatch`.

The merge order is a stable topological order over supplied dependency edges
for open PRs, with PR number as the deterministic tie-breaker. Merged and
closed PRs remain visible for ancestry/dependency evidence but are not merge
candidates. Cycles produce an empty order and the `merge_order_cycle` blocker.
The ordering is advisory evidence only.

## Ownership and Duplicate Authorities

The matrix reports exact changed-file collisions and a small list of existing
canonical authorities that are especially sensitive to parallel ownership:

- `scripts/ai/run_local_quality_gate.py`;
- `scripts/ai/pr_readiness_report.py`;
- `.github/workflows/agentic-quality-gate.yml`;
- `backend/economics/kernel.py`;
- `evaluation/trustos/client_workspace_isolation.py`;
- `evaluation/companyos/resource_execution_governor.py`.

It also reports duplicate sanitized `authority_claims`. These are indicators
for operator review, not a new ownership registry. The matrix does not assign
ownership, rewrite PRs, or resolve overlaps automatically.

## Local Evidence

Local evidence is preserved as supplied. `actual_executed` means the local
command executed; it does not mean a supplier, provider, customer, deployment,
or commercial operation was live validated. `fixture`, `manual`, `derived`,
and `simulated_or_planned` remain non-live, and are explicitly emitted with
`live_validated: false`.

`unavailable`, `ci_unavailable`, `not_run`, `failed`, `malformed`, and `blocked`
remain visible and contribute blockers where appropriate. The matrix never
upgrades a local classification to pass merely because a PR is present.

## Safety and Rollback

The implementation performs only bounded file reads and allowlisted local Git
identity reads. It does not write artifacts, use credentials, call providers,
modify worktrees, call GitHub, merge, close, approve, or mark PRs ready.

To roll back the implementation without rewriting history, revert its focused
commit on the feature branch and push the normal fast-forward update. Do not
use `git reset --hard`, force-push, or delete another worktree.
