# Active Plan: Reproducible Local Quality Gate v1

- **Plan ID:** `plan-reproducible-quality-gate-v1`
- **Task:** Normalize the existing MarketOS local quality gate into a deterministic, evidence-preserving check runner.
- **Branch:** `gpt/marketos-reproducible-quality-gate-v1`
- **Lane:** `jules`
- **Status:** `active`

## Objective

Extend the existing `scripts/ai/run_local_quality_gate.py` authority so another
operator can discover and, with explicit intent, execute local Python,
frontend, security, repository-state, and typed-analysis checks on Windows or
POSIX. Preserve the current planning API and keep all external actions
disabled.

## Scope

```json
{
  "in_scope": [
    "existing scripts/ai/run_local_quality_gate.py execution and reporting",
    "toolchain, dependency, lockfile, frontend, typed-analysis, CI-input, and git-state discovery",
    "structured check summaries with deterministic ordering and injected timestamps",
    "focused quality-gate regression coverage",
    "operator documentation"
  ],
  "out_of_scope": [
    "backend business logic or event contracts",
    "frontend application code",
    "provider integrations, browser automation, commerce, or deployment",
    "GitHub workflows or external CI querying",
    "automatic repair, merge, publishing, or dependency installation",
    "configuration normalization of the observed Python/Ruff mismatch",
    "CoderOS changes"
  ]
}
```

## Target Files

- `scripts/ai/run_local_quality_gate.py`
- `tests/test_local_quality_gate.py`
- `docs/ai/REPRODUCIBLE_QUALITY_GATE_V1.md`
- `docs/ai/QUALITY_GATES.md`
- `docs/ai/CODEX_OPERATING_MANUAL.md`
- `docs/plans/active/plan-reproducible-quality-gate-v1.md`

## Risk

```json
{
  "level": "MEDIUM",
  "mitigation": "The implementation stays in the existing local quality-gate script, uses shell=False with a fixed command allowlist, requires an injected timestamp for real execution, never installs or contacts external services, and stores only structured summaries. Missing tools, malformed configuration, unsafe frontend scripts, non-executed CI, and real command failures remain distinguishable. Existing planning APIs remain covered by the prior tests."
}
```

## Dependencies

```json
[
  {"id": "scripts/ai/operating_layer.py", "status": "resolved"},
  {"id": "scripts/ai/select_tests.py", "status": "resolved"},
  {"id": "scripts/ai/phase_gate.py", "status": "resolved"},
  {"id": "scripts/ai/pr_readiness_report.py", "status": "resolved"},
  {"id": "semgrep/ai-safety.yml", "status": "resolved"},
  {"id": "frontend/package.json", "status": "resolved"}
]
```

## Ownership

The existing `scripts/ai/run_local_quality_gate.py` remains the sole local
quality-gate authority. `operating_layer.py` remains the shared renderer and
Git helper. CI workflows, application modules, provider boundaries, and
deployment authorities are unchanged. Human review remains required.

## Verification Commands

- `python -m compileall repo_dev_runtime tests` is not applicable to this repository; use `python -m compileall scripts tests`.
- `python -m ruff check scripts tests`
- `python -m pytest -q tests/test_local_quality_gate.py tests/test_ai_dev_stack.py tests/test_agentic_operating_layer.py`
- `python scripts/ai/run_local_quality_gate.py --from-git --execute --generated-at 2026-08-28T12:00:00+00:00 --json`
- `python scripts/ai/run_local_quality_gate.py --from-git --generated-at 2026-08-28T12:00:00+00:00 --markdown`
- `python scripts/ai/session_finish.py --dry-run`
- `git diff --check`

## Evidence Checklist

- [ ] Toolchain and dependency state are reported without raw environment or transcript values.
- [ ] Compile, pytest, Ruff, typed, frontend, security, and diff checks have explicit statuses.
- [ ] Missing tools and failed tools have distinct results and exit behavior.
- [ ] CI failures with zero executed steps are unavailable rather than successful.
- [ ] Dirty and untracked state, secret redaction, malformed configuration,
      Python-version mismatch, deterministic replay, and dry-run behavior are tested.
- [ ] Real local execution output and fixture-injected output are clearly
      distinguished in the handoff.

## Stop Conditions

Stop without broadening scope if the change requires modifying business logic,
frontend application code, CI workflows, external network calls, provider
activation, dependency installation, automatic repair, merge/publish behavior,
or a second quality-gate authority. Stop if raw transcripts or credentials
would need to be stored, if a safe frontend command cannot be established, or
if unrelated files become part of the diff.
