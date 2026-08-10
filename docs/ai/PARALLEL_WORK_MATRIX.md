# Parallel Work Matrix

Updated: 2026-08-10

Codex is paused. Claude is the only active AI contributor; this matrix now exists primarily to record current
ownership so a future session (Claude or otherwise) doesn't duplicate or collide with in-flight review work.

| Owner | Paths | Current responsibility |
|---|---|---|
| Claude | `scripts/run_phase1_live_validation.py`, `docs/PHASE1_LIVE_VALIDATION_RUNBOOK.md` | Phase 1 intelligence stack (PR #149) and its live-validation harness (PR #150) are both merged to `main`. Only remaining Phase 1 work is running the harness from unrestricted network egress — see `docs/ai/SESSION_HANDOFF.md`. |
| Codex | — | Paused; no active ownership. Prior assignments below are historical, not current. |
| Shared | `docs/ai/SESSION_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md` | Coordinate before changing; latest committed handoff is the cross-environment source of truth |

## Do not start new Phase 1 feature work until live validation is attempted

PR #149 and PR #150 are both merged. The next branch (one of `claude/phase1-live-results`,
`claude/phase1-crawl4ai-js-extraction`, `claude/phase1-auth-readonly-supplier`, `claude/phase1-deployment-proof`)
depends on the outcome of running `scripts/run_phase1_live_validation.py --allow-network` from an unrestricted
environment — see `docs/ai/SESSION_HANDOFF.md`'s "Next action". Do not create any of those branches, or start
another intelligence module, until that outcome is known.

## Historical (pre-pause Codex assignments, no longer current)

Earlier matrix versions assigned Codex ownership of `backend/commerce/**`, `orchestrator/**`, commerce/orchestration
tests, `scripts/ai/**`, and performance benchmarks. Treat these as historical only — Codex is not currently active,
and Claude should not assume those paths are being watched by another agent.

Before editing a shared path, compare the remote branch and record the decision in the session handoff. Never
reset, rebase, or overwrite another agent's work.
