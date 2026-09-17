# Resume after AI-chat context compaction

Do not resume from chat memory. Resume from files.

## Required inputs

1. `MarketOS.AITask.v1` from `scripts/ai/operator_task_packet.py`
2. `MarketOS.AIContext.v1` from `scripts/ai/operator_context_snapshot.py` (#252)
3. `MarketOS.WorktreeSafety.v1` from `scripts/ai/worktree_safety.py`
4. `git worktree list`, `git status --short`, `git log -1 --oneline` in the packet worktree

## Procedure

1. Identify the exclusive worktree in the packet. Refuse the canonical dirty checkout.
2. Re-run the context snapshot with `--no-github` if `gh` is missing.
3. Re-run worktree safety. If `safe_to_edit` is false, stop.
4. Diff `changed_files` against `allowed_scope`.
5. Evaluate the last report with `agent_output_eval.py` before claiming progress.
6. Continue only the packet `next_action`.

## What memory must not replace

- HEAD / origin/main SHAs
- Open PR numbers and file ownership
- Quality-gate or phase-1 classifications
- Secret presence or absence
- CoderOS availability
