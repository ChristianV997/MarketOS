# Event Spine & Workspace Isolation Boundary Tests — Plan

- **Status:** active / completed this pass
- **Branch:** `claude/marketos-event-workspace-boundary-tests-v1`
- **Owner:** Claude (architecture-boundary lane)
- **Scope:** `tests/test_event_spine_boundaries.py`, `tests/test_workspace_isolation_boundaries.py`, one focused fix to `backend/workspaces/artifact_store.py`

## Objective

Add real, focused boundary coverage for the canonical event spine
(`backend/contracts/events.py`, `backend/events/repository.py`,
`backend/events/adapters/legacy.py`) and workspace isolation
(`backend/workspaces/**`), per `ARCHITECTURE_CONTRACT.md`'s event-spine
migration target and canonical-owner table — without introducing a second
event store, workspace manager, event schema, orchestration loop, approval
ledger, or quality gate.

## What was found and repaired

While writing the workspace-isolation coverage, a real, reproducible
path-traversal defect was found in `backend/workspaces/artifact_store.py`
(the canonical owner of workspace-scoped artifact storage): `path_for()`
and `list_experiments()` built filesystem paths via
`os.path.join(..., workspace_id, ..., experiment_id, ..., filename)` with
no validation on any of the three caller-supplied components. A
traversal-shaped `workspace_id` (e.g. `"../../../../tmp/evil"`) let
`ArtifactStore.save()` write a file completely outside `STATE_DIR`,
reproduced live before the fix. A narrower variant — a traversal-shaped
`experiment_id` or `filename` — stayed inside `state/workspaces/` after
normalization but landed in a different, attacker-chosen workspace
directory instead of the caller's own, which is the same boundary
violation in a subtler shape.

Per the smallest-repair exception in this PR's authorized scope, the fix
lives entirely in the canonical owner: a new `_reject_unsafe_component()`
helper rejects any of `workspace_id`/`experiment_id`/`filename` containing
an absolute-path prefix or a `..` path segment, called before any path is
constructed, plus a post-join prefix check as defense in depth. No new
persistence primitive, sanitizer module, or workspace manager was added —
`path_for()`, `save()`, `load()`, `save_text()`, `load_text()`, and
`list_experiments()` keep their existing signatures and return-value
contracts; `list_experiments()` specifically keeps its documented
never-raises/fail-to-empty-list behavior, while `save`/`load`/`save_text`/
`load_text` now raise `ValueError` on a rejected component (previously
untested, unreachable-by-legitimate-callers input, since real
`workspace_id`s are always `uuid5`-shaped via
`backend.vector.normalization.deterministic_id`).

## Reused canonical owners (no duplication)

- `backend/contracts/events.py::Event` — the canonical event envelope; not
  reimplemented or forked.
- `backend/events/repository.py::EventRepository` /
  `InMemoryEventRepository` / `JsonlEventRepository` — the append-only
  repository foundation; a new test (`test_only_backend_events_repository_
  defines_a_class_named_event_repository`) guards against a second
  `EventRepository`-named class being introduced anywhere in production
  code, complementary to (not a duplicate of) `tests/contracts/
  test_architecture_boundaries.py::test_event_store_locations_and_legacy_
  appenders_are_controlled`, which governs the older `event_store.py`/
  `event_store.log` naming pattern.
- `backend/events/adapters/legacy.py` — the sole approved read-only
  importer; both adapters' `append()` is confirmed to raise
  `NotImplementedError`.
- `backend/workspaces/client_workspace.py`, `registry.py`,
  `artifact_store.py` — workspace identity, lookup, and artifact storage;
  no second workspace manager introduced.
- `evaluation/trustos/client_workspace_isolation.py` and
  `evaluation/companyos/resource_execution_governor.py` — referenced with
  two light, non-duplicative assertions confirming their existing
  fail-closed safety invariants (`ClientWorkspaceSafetySummary.read_only`,
  `ExecutionDecisionResult.simulated_only`) rather than re-testing either
  module's own already-covered logic (`tests/test_client_workspace_
  isolation.py`, `tests/test_resource_execution_governor.py`).

## Definition of done (per `ARCHITECTURE_CONTRACT.md`)

1. **Reuse a canonical owner or document an approved exception.** Done —
   see above; the one production change is the smallest-repair exception
   this PR's scope explicitly allows, in the canonical owner itself.
2. **Keep dry-run, claim-safety, live-mode, and human-approval boundaries
   intact.** Done — `test_client_workspace_defaults_are_dry_run_and_not_
   live` confirms `ClientWorkspace`'s defaults; no live-mode, provider, or
   approval-ledger code was touched.
3. **Add or update a focused architecture/safety test when a new
   dependency or mutation path is introduced.** Done — this PR *is* that
   test addition; no new dependency was introduced (the fix uses only
   `os.path`, already imported in the file).
4. **Document any external dependency's source, license, and reason for
   use.** N/A — no new external dependency.
5. **Run focused tests, the repository policy checks available locally,
   and `git diff --check`.** Done — see Validation below.

## Validation

- `python -m compileall -q backend api scripts tests` — clean
- `ruff check backend/workspaces/artifact_store.py tests/test_event_spine_boundaries.py tests/test_workspace_isolation_boundaries.py` — clean
- `pytest tests/test_event_spine_boundaries.py tests/test_workspace_isolation_boundaries.py tests/test_workspaces/test_artifact_store.py tests/contracts/test_architecture_boundaries.py -q` — 56 passed, 0 failed
- `python scripts/ai/run_local_quality_gate.py --from-git --json` — `pr_merge_readiness: "ready_for_review"`, `phase_gate_status: "clear"`, `mutated: false`, `network_calls: false`, all `secret_or_artifact_flags` false
- `python scripts/ai/session_finish.py --dry-run` — passed (6 checks)
- `git diff --check` — clean
- Staged secret scan (`sk-`/`ghp_`/`AIza`/PEM private-key markers) — no matches
- AST-based scan of the three touched files for `shell=True`/`os.system`/`os.popen`/`eval`/`exec` — clean
- `semgrep` (named in the quality gate's recommended CI lanes) — **not available in this environment** (package-manager conflict blocked installation); not run, not simulated

## What this PR does not do

No new event store, workspace manager, event schema, orchestration loop,
approval ledger, or quality gate. No provider, network, payment, order, or
customer-message code touched. `scripts/ai/**`, `services/**`,
`frontend/**`, `.github/workflows/**`, and `pyproject.toml` are untouched.
