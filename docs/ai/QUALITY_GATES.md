# MarketOS Quality Gates

| Gate | Required evidence | Blocked work |
|---|---|---|
| Source safety | Explicit read-only/network gate and no secrets in output | credentialed or public calls by default |
| Architecture | Existing events, Commerce MVP, and provider boundary reused | duplicate event/client/orchestration path |
| Tests | Focused selector output plus regression checks | untested behavior change |
| PR hygiene | readiness report, `session_finish --dry-run`, clean diff | artifacts, `.env`, raw payloads, unrelated files |
| Phase 1 | `phase1_readiness_report.py` records live supplier/competition evidence or its exact operator blocker | supplier mutation/new provider/Phase 2 expansion |

Use `scripts/ai/phase_gate.py` for deterministic guardrails. It is advisory
planning infrastructure, not a replacement for human approval.

Before opening a PR, run `python scripts/ai/run_local_quality_gate.py --from-git --execute --generated-at <timezone-aware-ISO> --json`.
Planning mode is explicitly `not_run` and is not merge evidence. The same
local-only check runs on pull requests through
`.github/workflows/agentic-quality-gate.yml`; it writes a Markdown summary to
the GitHub job summary and never runs a live supplier or credentialed probe.

The quality-gate JSON includes the compact Phase 1 readiness score, blocking
gates, and deterministic next action. It remains useful in no-artifact mode;
missing proof is surfaced rather than fabricated.

## Reproducible local gate

`run_local_quality_gate.py` is the local quality-gate authority. It plans the
fixed check order `compile`, `pytest`, `ruff`, `typed`, `frontend`, `security`,
and `diff_check`; with `--execute` it runs only those repository-local checks.
It never installs dependencies, queries CI, calls providers, or publishes
raw command output. Use `--generated-at` to make the report timestamp an
explicit input, and use `--baseline-file` only for an operator-supplied
baseline whose check statuses are classified separately from the current run.

The structured report uses schema `MarketOS.LocalQualityGate.v2` and these
process exits:

| Exit | Meaning |
|---:|---|
| `0` | Executed checks passed. `ready_for_supervised_use` is still false unless all readiness conditions hold. |
| `1` | An observed check failure, security finding, timeout, blocked safety condition, or unverified failure origin. |
| `2` | A required tool/dependency is unavailable, checks were not run, or CI is unavailable/has no executed steps. |
| `3` | The report request or repository configuration is malformed. |

## CI preflight and final attestation

The existing workflow runs `--phase preflight`: it proves only that the
quality-gate authority's bounded compile, focused regression tests, focused
Ruff checks, and diff check executed successfully. Full repository tests,
Semgrep, and container validation remain owned by their existing CI jobs. A
preflight report always keeps
`ready_for_supervised_use` false and retains absent CI evidence as
`ci_unavailable`; its zero exit code is not final merge evidence. Final
attestation uses the default `final` phase with complete sanitized
`MarketOS.CIEvidence.v1` input after required jobs have completed.
When local execution fails while final CI evidence is absent, the local
failure classification remains visible; `ci_unavailable` does not mask it.

Failure classifications distinguish `changed_scope_failure` from
`pre_existing_failure` only when the injected baseline supports that claim.
Without baseline evidence, a failed check is `failure_origin_unverified`.
Missing tools, missing frontend dependencies, missing security policy, and CI
billing/zero-step states remain unavailable rather than becoming passes.
For sanitized CI metadata, pass a local JSON file with
`--ci-evidence-file <path>`. It must use schema `MarketOS.CIEvidence.v1` and
contain an explicit `required_jobs` list plus run status/conclusion and
required-job metadata: job name,
required flag, status, conclusion, runner id/name, executed-step count, log
availability, and required-check status. Unknown fields, including raw logs,
are malformed. A required job missing from the observed jobs is synthetic
`ci_unavailable` evidence. A missing runner, zero steps, incomplete job, or
unavailable logs is `ci_unavailable`; it cannot become a pass.
Malformed scanner output is malformed evidence. A security scanner that exits
zero while returning findings remains a security failure. The readiness field
stays false while any blocker exists, while the repository is dirty, or while
CI is not an observed success with executed steps.

The per-check status vocabulary is explicit: `passed`, `failed`, `unavailable`,
`timed_out`, `not_run`, `not_configured`, `collection_failed`, `blocked`, and
`malformed`. A pytest collection failure is separate from an ordinary test
failure; when its evidence contains a missing-import signal, its classification
is `unavailable_dependency`. A scanner that cannot produce valid structured
output is `security_scanner_failure`, and a failed `git diff --check` is
`diff_failure`. These classifications are observed evidence, not permission to
ignore the failed check.

For the full operator procedure, see
`docs/ai/REPRODUCIBLE_QUALITY_GATE_V1.md`.
