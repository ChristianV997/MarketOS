# Parallel Work Matrix

Updated: 2026-08-10

Codex is paused. Claude is the only active AI contributor; this matrix now exists primarily to record current
ownership so a future session (Claude or otherwise) doesn't duplicate or collide with in-flight review work.

| Owner | Paths | Current responsibility |
|---|---|---|
| Claude | `backend/mvp_commerce/opportunity_scoring.py`, `competition_intelligence.py`, `product_research.py`, `backend/adapters/research/competition_evidence.py`, their dashboard/API/CLI/docs surfaces | Phase 1 commerce intelligence stack — open as PR #149 (`claude/phase1-supplier-evidence` → `main`), CI green, awaiting review/merge decision |
| Codex | — | Paused; no active ownership. Prior assignments below are historical, not current. |
| Shared | `docs/ai/SESSION_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md` | Coordinate before changing; latest committed handoff is the cross-environment source of truth |

## Do not start overlapping work until PR #149's status is known

PR #149 covers Supplier Evidence, Opportunity Scoring, Competition Intelligence, and Product Research
Intelligence in one stacked branch. Before starting new work in any of the paths above, check the PR's current
state (open/merged/closed) — a new session should not open a second PR against the same branch or re-implement
capability this PR already provides.

## Historical (pre-pause Codex assignments, no longer current)

Earlier matrix versions assigned Codex ownership of `backend/commerce/**`, `orchestrator/**`, commerce/orchestration
tests, `scripts/ai/**`, and performance benchmarks. Treat these as historical only — Codex is not currently active,
and Claude should not assume those paths are being watched by another agent.

Before editing a shared path, compare the remote branch and record the decision in the session handoff. Never
reset, rebase, or overwrite another agent's work.
