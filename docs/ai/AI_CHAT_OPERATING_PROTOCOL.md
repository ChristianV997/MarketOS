# AI-chat operating protocol (Windows)

Read-only, fail-closed operating notes for AI coding chats. Do not invent a second quality gate, API client, evidence packet, or ranking algorithm.

Schema produced by the context utility: `MarketOS.AIContext.v1`.

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

Local checks never prove deployment readiness.

## Prohibited actions

- Do not edit the canonical dirty checkout.
- Do not stage `artifacts/`, `.env`, credentials, raw provider payloads, browser traces, or caches.
- Do not enable live providers, ads, orders, payments, messaging, or publishing.
- Do not run arbitrary shell strings. Use the explicit commands below.
- Do not merge PRs or mark them ready unless the operator asks.

## Repository preflight

```powershell
git -C C:\Users\HP\Documents\MarketOS fetch origin --prune
git -C C:\Users\HP\Documents\MarketOS status --short
git -C C:\Users\HP\Documents\MarketOS rev-parse HEAD
git -C C:\Users\HP\Documents\MarketOS rev-parse origin/main
python C:\Users\HP\Documents\MarketOS\scripts\ai\session_start.py --json
```

Proves: remote refs are current; canonical dirtiness is visible; HEAD/main SHAs are recorded; session ownership is captured. Does **not** prove a clean worktree.

## Current-state capture

```powershell
python C:\Users\HP\Documents\MarketOS.worktrees\ai-chat-operator-context-01\scripts\ai\operator_context_snapshot.py --json --no-github
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\HP\Documents\MarketOS.worktrees\ai-chat-operator-context-01\scripts\ai\operator_context_snapshot.ps1 -NoGitHub
```

Use the worktree path that owns the snapshot script. `--no-github` classifies GitHub as `not_run` instead of failing open. Nonzero exit means incomplete or unsafe context.

## Isolated worktree creation

```powershell
git -C C:\Users\HP\Documents\MarketOS fetch origin --prune
git -C C:\Users\HP\Documents\MarketOS worktree add -b cursor/<outcome> C:\Users\HP\Documents\MarketOS.worktrees\<outcome> origin/main
```

Proves: edits happen outside the dirty canonical checkout. Resume after context compaction by `git worktree list` and `git status` in that worktree only.

## Branch creation (after scope is clear)

```powershell
cd C:\Users\HP\Documents\MarketOS.worktrees\<outcome>
git switch -c cursor/<outcome>
```

Do not overlap an open PR's paths. Consult `docs/ai/PARALLEL_WORK_MATRIX.md`.

## Test selection

```powershell
python scripts/ai/select_tests.py --from-git --json
```

Proves: recommended commands for the current diff. Run only those commands plus the files you changed.

## Bounded validation

Frontend (when `frontend/` changed):

```powershell
cd frontend
npm test
npm run typecheck
npm run build
```

Backend smoke (when API/readiness paths changed):

```powershell
python -m pytest -q tests/test_frontend_api_dry_run_smoke.py
python scripts/phase1_readiness_report.py --json
```

Always:

```powershell
python -m compileall -q scripts tests
python -m ruff check scripts/ai tests/ai
python scripts/ai/session_finish.py --dry-run
git diff --check
```

`phase1_readiness_report.py --json` is blocked/unavailable until live supplier proof exists. Preserve those labels.

## PR inspection

```powershell
gh pr view 213 --json number,title,state,isDraft,headRefOid,baseRefOid
gh pr view 214 --json number,title,state,isDraft,headRefOid,baseRefOid
gh pr view 230 --json number,title,state,isDraft,headRefOid,baseRefOid
```

If `gh` or network is missing, report `unavailable`. Do not invent CI green.

## PR handoff

```powershell
git status --short
git diff --stat
git push -u origin HEAD
gh pr create --draft ...
```

Do not mark ready or merge. Final reports must include files changed, tests run, tests not run, evidence classes, rollback SHA, and one next operator action.

## Resume after context compaction

1. `git worktree list`
2. `git status --short` and `git log -1 --oneline` in the exclusive worktree
3. Re-run `operator_context_snapshot.py --no-github`
4. Do not reuse pasted SHAs from an old chat as live evidence

## Unavailable infrastructure

Report the tool, the command attempted, and `unavailable`. Never convert missing Node, Docker, GitHub, or credentials into `passed`.

## Rollback reference

```powershell
git switch --detach HEAD~
# or
git revert <sha>
```

Never hard-reset shared branches unless the operator explicitly requests it.
