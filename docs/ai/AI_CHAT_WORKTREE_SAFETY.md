# Worktree safety for AI-chat lanes

`scripts/ai/worktree_safety.py` is a read-only probe. It does not add, move, or
remove worktrees. It does not replace `session_start.py`.

## Checks

| Check | Fail condition |
| --- | --- |
| Dirty canonical checkout | Current tree matches the declared/env canonical path and `git status` is dirty |
| Existing worktree ownership | `git worktree list` shows other linked trees |
| Branch conflicts | Same branch checked out in another worktree, or `--expected-branch` mismatches |
| Duplicate file ownership | Allowed scope points at unsafe targets |
| Stale branch base | `merge-base HEAD origin/main` is not `origin/main` |
| Unsafe target paths | Absolute paths, `..`, `artifacts/`, `.git/` |
| Untracked sensitive files | Untracked `.env`, credential, or key-shaped names |

## Command

```powershell
python scripts/ai/worktree_safety.py --json `
  --canonical C:\Users\HP\Documents\MarketOS `
  --expected-branch grok/marketos-ai-chat-tooling-retrofit-v1 `
  --allowed-scope scripts/ai/operator_task_packet.py
```

Exit `2` means do not edit this tree. Create an exclusive worktree from
`origin/main` instead.

## Unavailable tools

Missing `git`, timed-out commands, and CoderOS probes are `unavailable`.
This utility never probes CoderOS live; record `coderos.classification=unavailable`.
