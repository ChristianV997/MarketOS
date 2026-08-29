# Plan: MarketOS Reproducible Quality Gate Repair v2

- **Plan ID:** `plan-marketos-quality-gate-repair-v2`
- **Task:** Repair the existing MarketOS local quality gate with truthful deterministic baseline and tool-availability reporting.
- **Branch:** `gpt/marketos-quality-gate-repair-v2`
- **Lane:** `antigravity`
- **Status:** `active`

## Objective

Repair the existing local quality-gate authority so its deterministic report
distinguishes observed passes, failures, unavailable tools/dependencies, CI
unavailability, malformed configuration, and unresolved failure origin. The
gate must expose truthful baseline, frontend, security, toolchain, dependency,
and repository-state evidence without persisting raw logs or enabling live
behavior.

## Scope

```json
{
  "in_scope": [
    "scripts/ai/run_local_quality_gate.py",
    "tests/test_local_quality_gate.py",
    "docs/ai/QUALITY_GATES.md",
    "docs/ai/REPRODUCIBLE_QUALITY_GATE_V1.md",
    "docs/plans/active/plan-marketos-quality-gate-repair-v2.md"
  ],
  "out_of_scope": [
    "backend, frontend application, services, providers, commerce, workflows, Docker, CoderOS, credentials, and unrelated tests",
    "automatic repair, dependency installation, network or CI queries, publishing, deployment, merge behavior, and live supplier or competition calls"
  ]
}
```

## Target Files

- `scripts/ai/run_local_quality_gate.py`
- `tests/test_local_quality_gate.py`
- `docs/ai/QUALITY_GATES.md`
- `docs/ai/REPRODUCIBLE_QUALITY_GATE_V1.md`
- `docs/plans/active/plan-marketos-quality-gate-repair-v2.md`

## Contracts

- `MarketOS.LocalQualityGate.v2` is the single structured report schema.
- `scripts/ai/run_local_quality_gate.py` remains the only local quality-gate authority.
- Existing `run()` advisory output remains backward-compatible for callers.
- The gate invokes only fixed local checks in stable order and never queries CI.

## Dependencies

```json
[
  {"id": "scripts_ai_operating_layer", "status": "resolved"},
  {"id": "scripts_ai_run_semgrep_policy", "status": "resolved"},
  {"id": "MarketOS local manifests and frontend metadata", "status": "resolved"}
]
```

## Risk

```json
{
  "level": "MEDIUM",
  "mitigation": "Extend the existing local-only gate without changing application code; use fixed commands, shell=False, transient output parsing, redacted summaries, explicit unavailable states, and human review before any merge or release."
}
```

## Ownership

The Antigravity governance lane owns this documentation and gate-reporting
slice. MarketOS application, provider, commerce, workflow, and CoderOS
authorities remain outside the lane. Human operators retain release, merge,
credential, and live-validation authority.

## Evidence

- Focused tests cover pass, changed-scope failure, pre-existing failure,
  unverified failure origin, missing tools, unavailable dependencies, frontend
  unavailability, security findings, timeout, malformed configuration, CI
  unavailability, baseline parsing, deterministic replay, and redaction.
- The final handoff records exact command exits, check classifications, real
  versus unavailable evidence, readiness, and safety-scan results.

## Stop Conditions

Stop without commit if the branch collides, the worktree is dirty, the change
requires protected CoderOS or MarketOS runtime files, the gate would query
external systems, raw logs or secrets would be persisted, or the diff
introduces generated-only material or unrelated refactors. Do not merge this
branch.

## Verification

- `python -m compileall scripts/ai tests`
- `python -m ruff check scripts/ai/run_local_quality_gate.py tests/test_local_quality_gate.py`
- `python -m pytest -q tests/test_local_quality_gate.py tests/test_ai_dev_stack.py tests/test_failure_classifier_ci.py tests/test_claim_safety.py tests/test_source_quality.py`
- `python scripts/ai/run_local_quality_gate.py --help`
- `python scripts/ai/run_local_quality_gate.py --from-git --generated-at 2026-08-29T12:00:00+00:00 --json`
- `python scripts/ai/session_finish.py --dry-run`
- `powershell -File scripts/verify.ps1` when present; otherwise report that no canonical script exists in this repository
- `git diff --check`
