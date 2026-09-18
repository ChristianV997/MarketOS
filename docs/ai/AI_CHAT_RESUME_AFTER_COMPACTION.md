# Resume after AI-chat context compaction

Do not resume from chat memory. Resume from files.

## Required inputs

1. `MarketOS.AITask.v1` from `scripts/ai/operator_task_packet.py`
2. `MarketOS.AIContext.v1` from `scripts/ai/operator_context_snapshot.py` (#252)
3. `MarketOS.WorktreeSafety.v1` from `scripts/ai/worktree_safety.py`
4. `git worktree list`, `git status --short`, `git log -1 --oneline` in the packet worktree

## Procedure

1. Refresh `origin/main` from the canonical checkout (`git fetch origin --prune`). Do not edit it.
2. Identify the exclusive worktree in the packet. Refuse the canonical dirty checkout.
3. Inspect dirty files with `git status --short` in that worktree only. Detached inspect worktrees make `select_tests.py --from-git` empty; use the named PR branch worktree.
4. Inspect PR ownership with `gh pr list` / `gh pr view`. If `gh` is missing, classify GitHub `unavailable`.
5. Re-run `MarketOS.AIContext.v1` (`operator_context_snapshot.py --no-github` or `marketos_ai_session.ps1 -Action snapshot -NoGitHub`).
6. Re-run worktree safety. If `safe_to_edit` is false, stop.
7. Declare scope from the packet `allowed_scope` / `prohibited_scope`. Diff `changed_files` against it.
8. Select tests with `select_tests.py --from-git --json` and run only those plus files you changed.
9. Evaluate the last report with `agent_output_eval.py` before claiming progress. Missing PR or report rollback fails closed.
10. Continue only the packet `next_action`. Handoff must include rollback SHA and one next action.

## What memory must not replace

- HEAD / origin/main SHAs
- Open PR numbers and file ownership
- Quality-gate or phase-1 classifications
- Secret presence or absence
- CoderOS availability
