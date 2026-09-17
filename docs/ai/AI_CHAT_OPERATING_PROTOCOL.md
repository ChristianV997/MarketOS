# AI-chat operating protocol (Windows)

Read-only, fail-closed operating notes for AI coding chats. Do not invent a second quality gate, API client, evidence packet, ranking algorithm, cockpit, or deployment engine.

Schema produced by the context utility: `MarketOS.AIContext.v1`.
Session entrypoint: `scripts/operators/marketos_ai_session.ps1`.

Canonical dirty checkout (do not edit): `C:\Users\HP\Documents\MarketOS`.
Exclusive worktrees live under `C:\Users\HP\Documents\MarketOS.worktrees\`.

## Evidence classification

Use these classes and never upgrade them:

| Class | Meaning |
|---|---|
| `actual` | Command ran on this host and succeeded |
| `simulated` | Existing offline/dry-run script output |
| `unavailable` | Tool, network, credentials, or endpoint missing |
| `not_run` | Intentionally skipped |
| `failed` | Ran and failed |
| `malformed` | Output could not be parsed safely |
| `blocked` | Policy rejected the action or payload |

Local checks never prove production or deployment readiness. Fixture, manual, and simulated success never become live proof.

## Authoritative surfaces (do not duplicate)

| Concern | Authority | Data class | Disabled / future |
|---|---|---|---|
| AI-chat repository context | `scripts/ai/operator_context_snapshot.py` (`MarketOS.AIContext.v1`) | mixed local `actual` + dry-run `simulated` | never production proof |
| AI-chat PowerShell session | `scripts/operators/marketos_ai_session.ps1` | wrapper; preserves child exit codes | never stages/deletes files |
| Product Validation sprints | PR #246 `scripts/operators/Invoke-MarketOSOperator.ps1` + `windows_operator_workflow.py` | dry-run / fixture | live/network/start flags rejected |
| First-phase intelligence runner | PR #228 `scripts/operators/run_first_phase_intelligence.ps1` | fixture/simulated packet | no ads/orders/payments |
| Frontend/API boundary | PR #213 `GET /api/phase1/readiness`, `/api/phase1/benchmark-matrix`, `/api/phase1/public-market-benchmark`, `/api/events/research-portfolio` | dry-run API | no provider calls from the browser |
| First-phase evidence cockpit | PR #230 `/operator/first-phase` | composed from #213; fixture/assumption/derived | `GET /api/phase1/evidence-cockpit` is future / not implemented |
| Deployment reliability | PR #249 dry-run container/reproducibility harness | dry-run | this lane does not execute deploy |
| Environment split | PR #253 (closed) `.cursor` bootstrap contract | metadata only | not an execution engine |
| CoderOS | `backend.adapters.coderos_readonly` | `plan_only` / `not_run` | `mode=probe` requires explicit opt-in |
| Quality gate | `scripts/ai/run_local_quality_gate.py` | local/dry-run | `--execute` is out of scope for the snapshot |

## Prohibited actions

- Do not edit the canonical dirty checkout.
- Do not stage `artifacts/`, `.env`, credentials, raw provider payloads, browser traces, caches, or customer data.
- Do not enable live providers, ads, orders, payments, messaging, or publishing.
- Do not run arbitrary shell strings. Use the explicit commands below.
- Do not merge PRs, force-push, deploy, or invoke the Merger Agent.
- Do not use destructive `git reset --hard`, `git checkout --`, or `git clean`.
- Do not touch user files outside the reserved exclusive worktree.

## 1. Inspect current state

```powershell
git -C C:\Users\HP\Documents\MarketOS fetch origin --prune
git -C C:\Users\HP\Documents\MarketOS status --short
git -C C:\Users\HP\Documents\MarketOS rev-parse HEAD
git -C C:\Users\HP\Documents\MarketOS rev-parse origin/main
git -C C:\Users\HP\Documents\MarketOS worktree list
python C:\Users\HP\Documents\MarketOS\scripts\ai\session_start.py --json
```

Then capture bounded context from the exclusive worktree that owns this lane:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\HP\Documents\MarketOS.worktrees\ai-chat-operator-context-01\scripts\operators\marketos_ai_session.ps1 -Action snapshot -NoGitHub
```

`--no-github` classifies GitHub as `not_run`. Nonzero snapshot exit means incomplete or unsafe context, not production failure.

## 2. Identify dirty files

```powershell
git status --short
git diff --stat
```

The snapshot `changed_paths` field already drops `artifacts/`, `.env`, caches, browser traces, and customer-shaped paths. Do not read or stage those files.

If `worktree.canonical_checkout` is true, stop editing. Reserve a worktree instead.

## 3. Reserve an isolated worktree

```powershell
git -C C:\Users\HP\Documents\MarketOS fetch origin --prune
git -C C:\Users\HP\Documents\MarketOS worktree add -b cursor/<outcome> C:\Users\HP\Documents\MarketOS.worktrees\<outcome> origin/main
cd C:\Users\HP\Documents\MarketOS.worktrees\<outcome>
git status --short
```

Proves: edits happen outside the dirty canonical checkout. Do not `git switch` inside the canonical tree to start work.

## 4. Claim file ownership

```powershell
python scripts/ai/session_start.py --json
```

Inspect `owned_path_changes`, `docs/ai/PARALLEL_WORK_MATRIX.md`, and:

```powershell
gh pr list --state open --limit 20 --json number,title,headRefName,files
```

If `gh` is missing, classify GitHub `unavailable` and compare local `git worktree list` plus open PR branches you already know. Do not overlap another open PR's paths. This lane owns `scripts/ai/operator_context_snapshot.py`, `scripts/operators/marketos_ai_session.ps1`, `docs/ai/AI_CHAT_OPERATING_PROTOCOL.md`, and `tests/ai/test_operator_context_snapshot.py`. It must not rewrite PR #246 operator workflow files or PR #230 cockpit UI.

## 5. Inspect another branch or PR without checkout mutation

```powershell
git fetch origin --prune
git log --oneline origin/main..origin/<branch> | Select-Object -First 20
git diff --stat origin/main...origin/<branch>
git rev-parse origin/main
git merge-base origin/main origin/<branch>
```

To inspect files, add a detached worktree instead of switching the current one:

```powershell
git -C C:\Users\HP\Documents\MarketOS worktree add --detach C:\Users\HP\Documents\MarketOS.validation\<pr-id> origin/<branch>
```

Compare a PR to `origin/main`:

```powershell
gh pr view 246 --json number,title,state,isDraft,headRefOid,baseRefOid,files
git diff --stat origin/main...c020c5c
```

Replace the SHA with the PR `headRefOid`. If `gh` is unavailable, report `unavailable` and do not invent CI green.

## 6. Detect branch drift

The snapshot `worktree.drift.vs_origin_main` is `aligned`, `ahead`, `behind`, `diverged`, or `unavailable`. Confirm with:

```powershell
git rev-parse HEAD
git rev-parse origin/main
git merge-base origin/main HEAD
```

Do not rebase onto `origin/main` unless the operator asks. Do not reset.

## 7. Identify worktree ownership

```powershell
git worktree list
git -C C:\Users\HP\Documents\MarketOS.worktrees\<outcome> branch --show-current
git -C C:\Users\HP\Documents\MarketOS.worktrees\<outcome> status --short
```

Ownership rule: one agent, one exclusive worktree, one PR branch. The snapshot `worktree.listed` array is a bounded view of other checkouts; it is not a license to edit them.

## 8. Select tests and run focused validation

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\operators\marketos_ai_session.ps1 -Action select-tests
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\operators\marketos_ai_session.ps1 -Action backend-check
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\operators\marketos_ai_session.ps1 -Action readiness
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\operators\marketos_ai_session.ps1 -Action final-check
```

Run frontend checks only when `frontend/` changed:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\operators\marketos_ai_session.ps1 -Action frontend-check
```

Stderr lines matching `MARKETOS_CLASSIFICATION` record `actual`, `simulated`, `unavailable`, `not_run`, `failed`, or `blocked`. Preserve the native exit code.

Always also acceptable as explicit Python:

```powershell
python scripts/ai/select_tests.py --from-git --json
python -m compileall -q scripts tests
python -m ruff check scripts/ai scripts/operators tests/ai
python scripts/ai/session_finish.py --dry-run
git diff --check
```

`phase1_readiness_report.py --json` is blocked/unavailable until live supplier proof exists. Keep those labels.

## 9. Report blockers

Lead with snapshot `blockers` and `next_best_action`. Include:

- dirty canonical checkout (do not edit it)
- overlapping open PR paths
- `unavailable` GitHub / CoderOS / npm
- quality-gate `ready_for_supervised_use: false`
- `deployment_not_proven_from_local_checks`

## 10. Create a PR

```powershell
git status --short
git diff --stat
git push -u origin HEAD
gh pr create --draft ...
```

Do not mark ready or merge. Final reports must include files changed, tests run, tests not run, evidence classes, rollback SHA, and one next operator action.

## 11. Hand off after context compaction

1. `git worktree list`
2. `git status --short` and `git log -1 --oneline` in the exclusive worktree
3. Re-run `marketos_ai_session.ps1 -Action snapshot -NoGitHub`
4. Re-read `docs/ai/AI_CHAT_OPERATING_PROTOCOL.md` and `docs/ai/PARALLEL_WORK_MATRIX.md`
5. Do not reuse pasted SHAs from an old chat as live evidence
6. Resume the same exclusive worktree; do not create a second snapshot authority

## 12. Clean up only an explicitly named worktree after approval

Default: leave worktrees in place.

After the operator names the path and approves removal:

```powershell
git -C C:\Users\HP\Documents\MarketOS worktree list
git -C C:\Users\HP\Documents\MarketOS worktree remove -- C:\Users\HP\Documents\MarketOS.worktrees\<outcome>
```

Refuse if the path is the canonical checkout, a `.validation` inspect tree still in use, or anything other than the exact approved path. Never `git worktree prune` as a shortcut for unnamed trees. Never `Remove-Item` a worktree.

## Unavailable infrastructure

Report the tool, the command attempted, and `unavailable`. Never convert missing Node, Docker, GitHub, CoderOS, or credentials into `passed`.

## Rollback reference

```powershell
git switch --detach HEAD~
# or
git revert <sha>
```

Never hard-reset shared branches unless the operator explicitly requests it.
