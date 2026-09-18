# MarketOS deployment readiness matrix

Status: evidence snapshot for `origin/main` `df59a0609897907c1565d7d5f78e20959095d430` updated in PR #249 (`grok/marketos-dev-deploy-reliability-v1`). This document does not authorize merge or live production.

Classification: `works`, `simulated`, `unavailable`, `blocked`, `not_run`.
Readiness: `ready_local_dry_run`, `ready_isolated_worktree`, `not_ready_staging`, `not_ready_operator`, `not_ready_public`, `blocked_live`.

No public or live-provider row is ready. Mutation gates remain default-off. Live provider actions require an evidence-backed Approval Ledger policy; do not commit secrets to .env or git.

## 1. Local dry-run

Works: offline scripts on main (`scripts/deployment_smoke_check.py --local`, `scripts/mvp_readiness.py`, `scripts/local_mvp_smoke.py`, `scripts/ingest_public_signals.py --fixtures`, `scripts/ai/check_dev_stack.py`, `scripts/ai/run_local_quality_gate.py --from-git`). Health contract is `/health` then `/ready`.
Simulated: unit-economics assumptions, commerce MVP fixtures, CompanyOS/TrustOS packs.
Credentials: none required (`no_credentials_required: True`).
Diagnostics: `python scripts/deployment_diagnostics.py --mode local_dry_run --json`.
Security: artifact-store traversal still described by #211. Mutation flags default-off.
Persistence: JSONL under `artifacts/`. Compose Postgres/Redis are provisioned for staging persistence.
Rollback: stop the process; delete fixture outputs only.
Cost: $0.
Readiness: `ready_local_dry_run`.

## 2. Isolated test worktree

Works: `git worktree add` against `origin/main` or one exclusive branch; `select_tests.py --from-git`.
Credentials: GitHub read.
Isolation: always preserve the canonical checkout; edit exclusively within `MarketOS.worktrees/<lane>`.
Security: do not share the dirty canonical Windows tree.
Rollback: `git worktree remove <worktree_path>`.
Readiness: `ready_isolated_worktree`.

## 3. Private staging

Works: `deploy/railway/railway.json`, `deploy/render/render.yaml`, `deploy/mvp/*`. Startup `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`. Default `MARKETOS_PUBLIC_COMMERCE_RUNS=0`.
Staging prerequisites (fail-closed via `backend.deployment.environment_contract`):
1. `ALLOWED_ORIGINS`: explicit private staging frontend URL (no wildcard `*`).
2. `DATABASE_URL` / `POSTGRES_PASSWORD`: strong non-default password (rejects `upos`, `postgres`, `admin`, `password`, `123456`).
3. `REDIS_URL`: valid connection string.
4. Mutation gates: `MARKETOS_PUBLIC_COMMERCE_RUNS=0`, `MARKETOS_ENABLE_LIVE_ACTIONS=0`.
5. Container dependency health: `redis` and `db` must pass `service_healthy`.
Rollback: previous platform revision; unset live flags.
Readiness: `not_ready_staging` (fail-closed until staging infrastructure is provisioned).

## 4. Authenticated operator deployment

Works: rate limits and request IDs on main; cockpit surfaces on unmerged #230.
Missing: session/auth middleware that blocks anonymous operator use.
Security: unauthenticated operator UI is not an authenticated deployment; #231 TrustOS export still open.
Readiness: `not_ready_operator`.

## 5. Public client-facing deployment

Works: Vercel + `VITE_API_BASE_URL` pattern; drafts stay `status: draft`.
Missing: auth, tenancy, webhook verification, WAF, distributed limits.
Security: isolation incomplete; mutation gates default-off is not a public-ready statement.
Readiness: `not_ready_public`.

## 6. Live provider activation

Works: fail-closed read-only adapter docs; Approval Ledger is the pre-integration gate.
Credentials: platform secret store only. Never `VITE_*` or git.
This lane performs no live action.
Readiness: `blocked_live`.

## Hardening in this lane (PR #249)

- Dockerfile `python:3.12-slim`, `USER marketos` (UID 10001), HEALTHCHECK `/health`, `STOPSIGNAL SIGINT`.
- Prod compose requires `POSTGRES_PASSWORD`, drops host 5432 publish, adds `service_healthy` dependencies, sets `MARKETOS_ENVIRONMENT: production`, keeps public-run `0`.
- Environment contract: `backend.deployment.environment_contract` verifies local dry-run, staging prerequisites, and rejects mutation flags fail-closed.
- Failure diagnostics: `backend.deployment.diagnostics` covers 11 actionable failure modes.
- High-value path harness: `scripts/run_high_value_path_harness.py` classifies `passed`, `failed`, `unavailable`, `not_run`, `blocked`, `malformed`, `timed_out` with zero live actions.
- Colab benchmark matrix: `scripts/run_high_value_path_harness.py --colab-matrix` measures 8 bounded paths with 100% deterministic bit-identity.
- Promotion rehearsal bundle: `backend.deployment.promotion_rehearsal` composes the environment contract, failure diagnostics, container checks, harness summary, CoderOS status, and CI classification into a sanitized deterministic bundle.
- Scenario fixtures: `backend.deployment.promotion_fixtures` covers deployment edge cases without credentials, providers, network, or mutations.
