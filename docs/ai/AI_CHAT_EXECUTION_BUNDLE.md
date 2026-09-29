# AI-chat execution bundle

`scripts/ai/execution_bundle.py` (`MarketOS.AIExecutionBundle.v1`) is the
seven-phase orchestrator that wires the existing AI-chat authorities into
one workflow. It is not a second context snapshot, quality gate, readiness
authority, event system, or CoderOS runtime.

## Authorities consumed, not duplicated

- `#252` `scripts/ai/operator_context_snapshot.py` (`MarketOS.AIContext.v1`) --
  consumed by reference via its `replay_hash`; never recomputed here.
- `scripts/ai/operator_task_packet.py` (`MarketOS.AITask.v1` /
  `MarketOS.AIResume.v1`) -- `prepare` and `handoff`.
- `scripts/ai/worktree_safety.py` (`MarketOS.WorktreeSafety.v1`) -- `admit`.
- `scripts/ai/select_tests.py` -- `select`.
- `scripts/ai/agent_output_eval.py` (`MarketOS.AgentEval.v1`) -- `evaluate`.

## Phases

1. `prepare(snapshot, task_packet_raw)` -- validate the packet against a
   #252 snapshot's `replay_hash`; warns (never silently accepts) if the
   packet's `base_sha` isn't in the snapshot's `HEAD`/`origin_main`.
2. `admit(root, task_packet, ...)` -- `worktree_safety.evaluate_safety`.
3. `select(task_packet)` -- `select_tests.select(allowed_scope)`.
4. `execute(commands, ...)` -- the one new safety-critical surface: an
   allowlisted, non-shell command runner. `argv[0]` must be a bare command
   name (`python3`, `pytest`, `ruff`, `git`); a path-qualified executable
   (e.g. `/tmp/evil/git`) is rejected outright, never resolved and run.
   Every command is classified into exactly one of `executed`, `passed`,
   `failed`, `unavailable`, `not_run`, `skipped`, `malformed`, `timed_out`,
   `ci_unavailable`. Duplicate commands in one batch collapse by
   most-severe-wins (a `failed` is never hidden behind a later `passed`).
5. `evaluate(report, task_packet, ...)` -- `agent_output_eval.evaluate_report`.
6. `handoff(...)` -- builds a `MarketOS.AIResume.v1` packet plus a
   copy-paste command manifest rendered in both POSIX and PowerShell form
   (`render_command`; informational only, never auto-executed) plus a
   compact human-readable block.
7. `pr_check(task_packet, pr_reference, pr_changed_files)` -- validates a PR
   reference exists and its changed paths stay inside `allowed_scope`.
   Makes no network call itself; `pr_changed_files` is caller-supplied.

## Safety model

- `shell=False` always; argv is always a list, never a shell string.
- A fixed executable allowlist (`python3`/`python` restricted to
  `-m pytest|compileall|ruff|...`, bare `pytest`/`ruff`, and `git` restricted
  to `diff --check` / `status --porcelain` / `rev-parse HEAD`) plus a
  denylist regex (`rm -rf`, `--force`, `reset --hard`, credential/`.env`
  paths, shell metacharacters) checked before any subprocess call.
- Output is redacted for secret-shaped content and capped.
- `execute` never deletes files, force-pushes, or reads credentials.

## Public pattern credit

See the module docstring in `scripts/ai/execution_bundle.py` for the full
per-source URL/license/pattern/decision table (OpenHands, Aider, SWE-agent,
Open Policy Agent, OpenTelemetry, OpenLineage, reproducible-builds.org --
concepts only, nothing vendored).
