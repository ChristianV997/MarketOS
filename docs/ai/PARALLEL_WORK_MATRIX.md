# Parallel Work Matrix

Updated: 2026-08-01

This matrix prevents Codex and Claude from editing the same subsystem without coordination.

| Owner | Paths | Current responsibility |
|---|---|---|
| Claude | `docs/archive/**`, `.github/workflows/codeql.yml`, `docs/CRM_CANDIDATE_RESEARCH.md`, `services/sales_automation/**`, sales-automation docs/tests | Historical-doc sweep, CodeQL, CRM research, Chatwoot sales handoff |
| Codex | `scripts/ai/**`, `docs/ai/PARALLEL_WORK_MATRIX.md`, performance benchmark scripts/tests/workflow | Synchronization, performance baselines, AI-tool beta workflow |
| Shared | `docs/ai/SESSION_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md` | Coordinate before changing; latest committed handoff is the cross-environment source of truth |

Before editing a shared path, compare the remote branch and record the decision in the session handoff. Never reset, rebase, or overwrite another agent's work.
