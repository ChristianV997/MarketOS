# Developer snapshot: reproduce MarketOS without guessing

Lane: `grok/marketos-dev-deploy-reliability-v1`
Base: `origin/main` `df59a0609897907c1565d7d5f78e20959095d430`
Posture: no live actions, no merge, no second quality gate.

## Exclusive worktree (required)

Preserve the canonical dirty checkout. Do not run agents inside it.

```powershell
git fetch origin --prune
git worktree add C:\Users\HP\Documents\GitHub\MarketOS-wt-deploy origin/main
Set-Location C:\Users\HP\Documents\GitHub\MarketOS-wt-deploy
git switch -c grok/marketos-dev-deploy-reliability-v1
```

Linux / this sandbox equivalent (when a clone exists):

```bash
git fetch origin --prune
git worktree add /tmp/marketos-wt origin/main
cd /tmp/marketos-wt
```

## Inventory commands

```powershell
git rev-parse HEAD
git status --short
gh pr list --state open --limit 30
git worktree list
python scripts/ai/session_start.py --json
python scripts/ai/check_dev_stack.py --json
python scripts/phase1_readiness_report.py --json
python scripts/ai/select_tests.py --from-git --json
```

## Tests that exist on main (run on the worktree)

Backend / contracts:

```powershell
python -m compileall backend api evaluation scripts tests
python -m pytest -q tests/contracts/test_deployment_env_contract.py tests/contracts/test_cors_validation.py tests/contracts/test_mvp_mode.py tests/contracts/test_architecture_boundaries.py
python -m pytest -q tests/contracts/test_container_hardening.py tests/test_high_value_path_harness.py
```

Frontend on **main** only has `dev` / `build` / `preview`. `npm test` and the lockfile belong to open draft #213 — treat them as `unavailable` on main, not failed.

```powershell
if (Test-Path frontend/package-lock.json) { Set-Location frontend; npm ci --ignore-scripts --no-audit --no-fund; npm run build }
```

Quality gate (existing, do not replace):

```powershell
python scripts/ai/run_local_quality_gate.py --from-git --generated-at 2026-09-17T21:00:00-06:00 --ci-status unavailable --ci-steps 0 --json
python scripts/ai/session_finish.py --dry-run
git diff --check
```

Ruff is advisory (`ARCHITECTURE_CONTRACT.md`). If `ruff` is missing, record `unavailable`.

## Deployment descriptors

```powershell
python scripts/deployment_smoke_check.py --local --json
python scripts/mvp_readiness.py --json
python scripts/run_high_value_path_harness.py --json
```

Parse-only checks for Render/Railway live in `tests/contracts/test_deployment_env_contract.py` and `tests/contracts/test_container_hardening.py`.

## Performance harness

```powershell
python scripts/run_high_value_path_harness.py --json
python scripts/benchmark_commerce_cycle.py --runs 5
```

The new harness times fixture-sized paths and classifies missing modules as `unavailable` / `not_run`. It does not optimize and does not call providers. Existing `scripts/benchmark_commerce_cycle.py` remains the commerce-cycle authority when the full stack imports.

## AI-chat continuation protocol

1. Read this file, `docs/DEPLOYMENT_READINESS_MATRIX.md`, and `AGENTS.md`.
2. `git fetch origin --prune` and confirm `origin/main`.
3. Use an exclusive worktree. Do not touch the dirty canonical tree.
4. Do not open a same-scope PR on artifact-store (#211), quality-gate (`scripts/ai/run_local_quality_gate.py`), frontend API boundary (#213), Windows operator workflow (#246), profit kernel (#248), or research-to-decision (#247).
5. Classify evidence: `actual_executed` / `unavailable` / `not_run` / `ci_unavailable` / `blocked`.
6. Never merge. Never claim production readiness from local evidence.
7. No `--allow-network`, no provider flags, no `.env` commits, no `artifacts/` staging.

## Rollback

```powershell
git switch main
git worktree remove C:\Users\HP\Documents\GitHub\MarketOS-wt-deploy
```

If this branch was pushed: close the draft PR unmerged and delete the branch. Revert Dockerfile / compose by restoring main blobs. No database migration is introduced.

## No-live-action statement

This lane did not deploy, did not call providers, did not write credentials, did not open public endpoints, and did not merge.
