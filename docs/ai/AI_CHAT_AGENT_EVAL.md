# Agent output evaluation

`scripts/ai/agent_output_eval.py` checks an AI-chat final report against a
validated `MarketOS.AITask.v1` packet. It is not `run_local_quality_gate.py`
and it is not `pr_readiness_report.py`.

## Rules

1. Claims of passing tests must list the executed commands.
2. `unavailable` / `not_run` / `ci_unavailable` must not be reported as `passed`.
3. Fixture or simulated evidence must not be labeled live.
4. `changed_files` must stay inside `allowed_scope`.
5. The report must cite a PR.
6. Rollback must exist on the report or the packet.
7. Reserved authority files must not be rewritten.
8. Secret-shaped strings fail the eval.
9. "Full suite passed" requires an actual full-suite command.

## Command

```powershell
python scripts/ai/agent_output_eval.py --json `
  --packet docs/ai/examples/task-packet.json `
  --report artifacts-local-only/report.json
```

Do not write reports under the repository `artifacts/` tree from this lane.
