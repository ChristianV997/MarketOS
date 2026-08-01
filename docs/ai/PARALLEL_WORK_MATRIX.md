# Parallel Work Matrix

Updated: 2026-08-01

This matrix prevents Codex and Claude from editing the same subsystem without coordination.

| Owner | Paths | Current responsibility |
|---|---|---|
| Claude | Completed merged work on `origin/main` | Historical-doc sweep, CodeQL, CRM research, Chatwoot sales handoff; do not recreate these artifacts |
| Codex | `backend/commerce/feedback.py`, `orchestrator/main.py`, focused feedback/orchestration tests | Canonical real-metrics observation bridge, deduplication, and learning-loop verification |
| Shared | `docs/ai/SESSION_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md` | Coordinate before changing; latest committed handoff is the cross-environment source of truth |

Before editing a shared path, compare the remote branch and record the decision in the session handoff. Never reset, rebase, or overwrite another agent's work.
