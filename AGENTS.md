# AI Development Policy

- Use the smallest sufficient context: inspect symbols and direct references before full files.
- Search for existing equivalent functionality before creating a module.
- Use architecture tools only for architecture work, current documentation tools only for external APIs, and bounded repository snapshots only for external-repository evaluation.
- Do not install MCP servers or skills globally.
- Do not enable live external actions without approval and safety gates.
- Distinguish implemented, tested, dry-run, integration-tested, and live-validated capability.
- Update repository-specific AI memory after significant architecture changes.

## Token-efficient workflow

- Read `docs/ai/CANONICAL_ARCHITECTURE.md` and `docs/ai/CANONICAL_PATHS.md` before broad discovery.
- Use `scripts/ai/check_dev_stack.py` for capability checks and `scripts/ai/generate_session_handoff.py` at session boundaries.
- Run `scripts/ai/session_start.py --json` before editing and consult `docs/ai/PARALLEL_WORK_MATRIX.md` to avoid overlapping Claude-owned work.
- Run `scripts/ai/session_finish.py --dry-run` before committing; run the deterministic inference and commerce benchmarks when changing performance-sensitive paths.
- Before selecting a new Phase 1 feature, run `python scripts/phase1_readiness_report.py --json`; follow its single `next_best_action` unless the operator explicitly changes phase.
- When credentials are absent, prefer the offline marketplace and supplier-feasibility import layers for report value; never label fixture/manual supplier evidence as live proof.
- Filter large test and Semgrep logs with `scripts/ai/filter_test_output.py` and `scripts/ai/filter_semgrep_output.py`.
- Use architecture/dependency tooling only for architecture work; use current external documentation only for version-sensitive APIs.
- Do not install or enable third-party MCP servers, skills, models, or plugins without review.

## Codex operating rules

- Start with `git fetch origin`, `git switch main`, `git pull --ff-only origin main`,
  `git status --short`, and `gh pr list --state open`. Do not overlap an open
  PR's paths; create `codex/<outcome>` branches only after the scope is clear.
- Keep the canonical architecture intact: one event spine, one Commerce MVP
  path, existing provider clients, and no parallel orchestration/scoring.
- Treat network, credentials, provider calls, spending, publishing, orders,
  inventory, payments, and customer messages as default-off. State whether a
  result is fixture-tested, dry-run, integration-tested, or live-validated.
- Never stage `artifacts/`, `.env`, credentials, raw provider payloads, browser
  traces, cache files, or unrelated dirty-worktree changes. Stage explicit
  paths only.
- Use `scripts/ai/select_tests.py --from-git --json` before choosing tests and
  `scripts/ai/run_local_quality_gate.py --from-git --json` plus
  `scripts/ai/pr_readiness_report.py --json` before opening a PR. Run
  `session_finish.py --dry-run` and `git diff --check` before committing.
- Use `gh` for PR state/checks/merge only after local scope and safety review.
  Use web research only for version-sensitive external APIs; cite primary docs.
- Final reports lead with outcome and include scope, changed files, test commands
  and results, unrun checks, safety/no-mutation confirmation, risk/rollback,
  PR status, and the next single operator action.
