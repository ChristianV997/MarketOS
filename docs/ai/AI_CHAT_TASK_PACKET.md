# MarketOS.AITask.v1

Machine-readable handoff for one AI-chat software lane. This is not a second
quality gate, PR-readiness report, Governor, TrustOS export, or context snapshot.

Context snapshots remain `MarketOS.AIContext.v1` from
`scripts/ai/operator_context_snapshot.py` (open draft #252). Use both documents
together; do not merge their schemas.

## Command

```powershell
python scripts/ai/operator_task_packet.py --json --validate path\to\packet.json
python scripts/ai/operator_task_packet.py --json `
  --agent-id grok-ai-development-tooling-engineer `
  --source-chat "Grok Chat" `
  --lane AI-CHAT-DEVELOPER-TOOLING-RETROFIT-V1 `
  --objective "Add task packet and worktree safety" `
  --allowed-scope scripts/ai/operator_task_packet.py `
  --base-sha df59a0609897907c1565d7d5f78e20959095d430 `
  --worktree C:\Users\HP\Documents\MarketOS.worktrees\ai-chat-tooling `
  --rollback "close draft PR; delete branch; restore origin/main" `
  --next-action "human review of exclusive files"
```

Nonzero exit means the packet is malformed or unsafe. The utility never
upgrades `unavailable` to `passed`.

## Required fields

| Field | Meaning |
| --- | --- |
| `agent_id` | Specialist identity |
| `source_chat` | Chat or control-room origin |
| `lane` | Exclusive lane id |
| `objective` | One bounded software outcome |
| `allowed_scope` | Relative paths this lane may edit |
| `prohibited_scope` | Paths and capabilities that stay off-limits |
| `base_sha` | Git SHA the worktree must start from |
| `worktree` | Exclusive worktree path, never the dirty canonical checkout |
| `dependencies` | Documents or PRs that must stay file-disjoint |
| `acceptance_criteria` | Checks a reviewer can re-run |
| `selected_tests` | Exact commands, not "full suite" unless that command ran |
| `evidence_classification` | `actual` / `simulated` / `unavailable` / `not_run` / `failed` / `malformed` / `blocked` / `fixture` / `ci_unavailable` |
| `rollback` | How to discard the branch without touching `main` |
| `next_action` | Single operator step |

## Rejected packets

- Secret-shaped values or credential key names
- Paths under `artifacts/`, `.env`, `credentials/`, caches, browser traces
- Absolute paths or `..` traversal
- Claims that this packet replaces quality-gate, Governor, TrustOS, or #252
- Allowed scope that rewrites reserved authority files

## Resume after compaction

1. Re-read this packet and the latest `MarketOS.AIContext.v1`.
2. `git worktree list` and `git status --short` in the packet `worktree`.
3. Confirm `HEAD` ancestry against `base_sha` and `origin/main`.
4. Do not trust SHAs pasted in an old chat if the snapshot disagrees.
