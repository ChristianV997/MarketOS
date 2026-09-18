# Plan: MarketOS artifact-store security v3

- Status: active / implemented this pass
- Branch: `grok/marketos-artifact-store-security-v3`
- Scope: `backend/workspaces/artifact_store.py`, `tests/test_workspaces/test_artifact_store.py`, this plan, `docs/security/workspace-artifact-boundary.md`

## Finding

Current `origin/main` (`f0cfdb83487306ea434d50cdd1dcc8280134815e`) joins
caller-supplied `workspace_id` / `experiment_id` / `filename` into
`state_path(...)` with no validation. Reproduced in an isolated temp root:

- `workspace_id="../../../../tmp/evil-artifact-repro-v3"` normalizes to
  `/tmp/evil-artifact-repro-v3/experiments/exp-1/x.json` and `save()` wrote
  that file outside `STATE_DIR`
- `filename="/etc/passwd"` becomes an absolute path because `os.path.join`
  discards prior segments
- `experiment_id="../workspace-b"` lands in a sibling workspace directory

PR #196 and PR #206 contained this class of repair and were closed unmerged.
This vehicle stays inside the artifact-store file scope and does not revive
event-spine changes from #196.

## Repair

Validate every component before join. Require workspace and experiment
identities to be a single segment. Resolve the joined path with `commonpath`
against `state/workspaces`. Reject symlink parents that realpath outside the
sandbox. Redact credential-shaped JSON keys/values. Keep existing method
signatures and `list_experiments()` fail-to-`[]` behavior.

## Out of scope

No second event store, workspace registry, quality gate, orchestration loop,
or CoderOS integration. No merge.
