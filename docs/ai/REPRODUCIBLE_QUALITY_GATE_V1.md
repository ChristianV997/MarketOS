# Reproducible Local Quality Gate v1

`scripts/ai/run_local_quality_gate.py` is the canonical local quality-gate
entrypoint. It extends the existing AI-tooling layer; it is not a second CI
system, a repairer, or a publishing authority.

## Invocation

Use a dry run to inspect configuration and the fixed command plan without
claiming that checks passed:

```text
python scripts/ai/run_local_quality_gate.py --from-git --generated-at 2026-08-28T12:00:00+00:00 --json
```

Use real local execution only with an explicit timezone-aware timestamp:

```text
python scripts/ai/run_local_quality_gate.py --from-git --execute --generated-at 2026-08-28T12:00:00+00:00 --json
```

`--markdown` emits the same report as an operator-readable document. `--output`
may write that rendered report to an explicit path. The gate never installs
dependencies, clones repositories, contacts GitHub, calls providers, or
persists command transcripts.

## Report Contract

The JSON report uses schema `MarketOS.LocalQualityGate.v2` and has a stable
check order:

1. Python compile
2. pytest
3. Ruff
4. mypy or pyright when configured
5. frontend lint, typecheck, test, and build when declared
6. Semgrep when `semgrep/ai-safety.yml` exists
7. `git diff --check`

Each check reports `passed`, `failed`, `missing`, `unavailable`,
`not_configured`, `not_run`, or `blocked` as appropriate. It records exit code,
tool availability, and bounded numeric summaries only. Raw stdout and stderr
are intentionally absent from the report.

Each check also has a deterministic `classification`. Passing checks use
`pass`; missing executables use `missing_tool`; absent installed dependencies
use `unavailable_dependency`; Semgrep findings use `security_finding`; command
timeouts use `timeout`; and malformed inputs use `malformed_configuration`.
A failed local check is classified as `changed_scope_failure` or
`pre_existing_failure` only when the operator supplies explicit baseline
evidence. Without that evidence it is `failure_origin_unverified`, never an
invented attribution. The aggregate report retains all classifications in
`failure_classes` so baseline Ruff findings and other blockers remain visible.

Stable process exit codes are:

| Code | Meaning |
| --- | --- |
| 0 | Checks passed, passed with warnings, or a non-executing dry run |
| 1 | An executed check failed or found a security violation |
| 2 | A required tool, dependency, or external CI evidence is unavailable |
| 3 | Configuration or timestamp input is malformed or incomplete for execution |

Exit code `0` in dry-run mode does not mean the repository passed. The report
sets `mode` to `dry_run`, `status` to `dry_run`, and
`ready_for_supervised_use` to `false`.

## Discovery and Alignment

The gate reports the selected interpreter by version and redacted executable
basename, then compares `.python-version`, Docker `FROM python:` versions,
CI `python-version` declarations, and Ruff's `target-version`. It also reports
requirements manifests, exact lockfiles, and the number of non-exact
requirements without copying dependency contents.

The current repository intentionally reports an alignment warning: the local
`.python-version` and some CI declarations use Python 3.12, Docker uses 3.14,
and Ruff targets `py311`. This mission reports the mismatch; it does not
silently normalize configuration. A future toolchain-normalization change
must be separately planned and reviewed.

Frontend checks are metadata-driven. A package manifest without a lockfile is
reported as incomplete. Missing `node_modules` is `unavailable`, and no network
installation is attempted. Only declared scripts containing the local build or
test tool allowlist are eligible to run; scripts containing provider, network,
credential, deployment, or installation markers are blocked.

## CI and Repository State

The gate never queries external CI. Operators may inject a CI result with
`--ci-status` and `--ci-steps` or through `ci_result` in Python. A failure with
zero executed steps is classified as `unavailable`, not as a test failure or a
  pass, and carries the `ci_unavailable` classification. Local dirty and
  untracked state is reported as counts, without retaining
the raw status transcript.

To attribute a new failure to a changed scope, provide a prior structured gate
report through `--baseline-file`. The file is reduced to check names and status
values; its raw contents are never copied into the output. A current failure
against a baseline `passed` check and a non-empty changed scope is a
`changed_scope_failure`. A baseline `failed` check is `pre_existing_failure`.
If the baseline is absent or does not identify the check, the origin remains
unverified and readiness stays false.

## Safety and Evidence Modes

- `dry_run` is a plan/configuration report only.
- `real_execution` runs only the fixed local commands from the report.
- `network_used`, provider calls, credential reads, automatic repair, merge,
  and publish flags are always false.
- Missing tools are never converted to successful checks.
- Command output is parsed transiently into counts and presence booleans;
  stdout, stderr, environment values, and secret-shaped values are not saved.
- The gate does not claim that external CI or a live MarketOS deployment ran.

## Verification

The focused regression suite is:

```text
python -m pytest -q tests/test_local_quality_gate.py tests/test_ai_dev_stack.py tests/test_agentic_operating_layer.py
```

The repository verification wrapper remains:

```text
powershell -File scripts/ai/session_finish.py --dry-run
```

The quality gate is a local evidence producer for supervised review. It is not
itself approval to merge, deploy, spend, publish, place orders, or activate a
provider.
