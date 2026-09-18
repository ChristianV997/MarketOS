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

## Deployment descriptors and failure diagnostics

```powershell
# Offline deployment and readiness smoke checks
python scripts/deployment_smoke_check.py --local --json
python scripts/mvp_readiness.py --json

# Actionable failure diagnostics (covers 11 failure modes)
python scripts/deployment_diagnostics.py --mode local_dry_run --json

# To diagnose private staging readiness:
python scripts/deployment_diagnostics.py --mode staging --json
```

## Performance harness & Colab benchmark matrix

```powershell
# Bounded deterministic path measurement
python scripts/run_high_value_path_harness.py --json

# Run the 8-path Colab benchmark matrix (local actual_executed or Colab managed):
python scripts/run_high_value_path_harness.py --colab-matrix --runs 3
```

### How to interpret harness classifications

1. `passed`: The path executed bounded deterministic logic to completion, validated its output against schema/expectations, and verified bit-identical replay fingerprint.
2. `failed`: The path attempted execution but raised an unhandled exception or failed an assertion. **Failures are never downgraded to unavailable.**
3. `unavailable`: The required module, CLI tool, or fixture file was absent prior to execution (e.g. absent optional provider or missing native package).
4. `not_run`: The path module is present in the repository, but execution was intentionally skipped (e.g. reserved for operator local fixture path without synthetic candidate generation).
5. `blocked`: A safety gate or policy stopped execution (e.g. live commerce runs or mutation flags enabled without authorization).
6. `malformed`: The input fixture or output record failed schema structure validation.
7. `timed_out`: Path execution exceeded the bounded timeout threshold.

### How to reproduce the Colab benchmark matrix

Run:
```bash
python scripts/run_high_value_path_harness.py --colab-matrix --runs 3
```
Expected summary results on synthetic fixture data (0 secrets, 0 network, 0 live mutations):
- `unit_economics`: passed, ~0.05ms, bit_identity=True (1 unique hash across runs)
- `supplier_import_normalization`: passed, ~0.01ms, bit_identity=True
- `product_opportunity_synthesis`: passed, ~0.001ms, bit_identity=True
- `competition_normalization`: passed, ~0.008ms, bit_identity=True
- `commerce_dry_run_cycle`: passed, ~0.001ms, bit_identity=True
- `report_export_generation`: passed, ~0.002ms, bit_identity=True
- `replay_idempotency`: passed, ~0.028ms, bit_identity=True
- `container_contract_parsing`: passed, ~0.000ms, bit_identity=True
- `dependency_unavailable_behavior`: passed, ~0.000ms, bit_identity=True

## Private staging prerequisites

Before attempting a private staging deployment, verify via `backend.deployment.environment_contract`:
1. `ALLOWED_ORIGINS`: explicit private staging URL (no wildcard `*`).
2. `DATABASE_URL` and `POSTGRES_PASSWORD`: strong non-default password (rejects `upos`, `postgres`, `admin`, `password`, `123456`).
3. `REDIS_URL`: valid connection string.
4. Mutation gates: `MARKETOS_PUBLIC_COMMERCE_RUNS=0`, `MARKETOS_ENABLE_LIVE_ACTIONS=0`.
5. Container dependency health: `redis` and `db` services configured with `condition: service_healthy`.

## AI-chat continuation protocol

1. Read this file, `docs/DEPLOYMENT_READINESS_MATRIX.md`, and `AGENTS.md`.
2. `git fetch origin --prune` and confirm `origin/main`.
3. Use an exclusive worktree. Do not touch the dirty canonical tree.
4. Do not open a same-scope PR on artifact-store (#211), quality-gate (`scripts/ai/run_local_quality_gate.py`), frontend API boundary (#213), Windows operator workflow (#246), profit kernel (#248), or research-to-decision (#247).
5. Classify evidence: `actual_executed` / `unavailable` / `not_run` / `ci_unavailable` / `blocked`.
6. Never merge. Never claim production readiness from local evidence.
7. No `--allow-network`, no provider flags, no `.env` commits, no `artifacts/` staging.

## Known unavailable checks

- **Google Colab compute**: Not mounted or connected on local workstation (`unavailable`); synthetic benchmark matrix runs locally as `actual_executed`.
- **CoderOS CLI**: Probed via `backend.adapters.coderos_readonly.probe()`; reported `unavailable` (no `coderos` executable/root).
- **ECC / gstack / Hermes**: CLI and skills are not installed in the environment (`unavailable`).
- **Remote CI**: Zero-step / `ci_unavailable`. Local quality gate `--from-git` is the canonical verification authority.

## Promotion rehearsal bundle

The offline promotion rehearsal composes existing deployment authorities into a deterministic, sanitized readiness record:

```powershell
python scripts/deployment_diagnostics.py --promotion-rehearsal --env local_dry_run --json
python scripts/deployment_diagnostics.py --promotion-rehearsal --fixture clean_local_dry_run --json
```

It redacts secret-shaped values, keeps CI with zero executed steps as `ci_unavailable`, and never enables providers or live mutations.

## Rollback

```powershell
git switch main
git worktree remove C:\Users\HP\Documents\MarketOS.worktrees\dev-deploy-reliability-v1
```

If this branch was pushed: close the PR unmerged and delete the branch. Revert Dockerfile / compose by restoring main blobs. No database migration is introduced.

## No-live-action statement

This lane did not deploy, did not call providers, did not write credentials, did not open public endpoints, did not spend funds, and did not merge.
