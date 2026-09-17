# MarketOS deployment readiness matrix

Status: evidence snapshot for `origin/main` `df59a0609897907c1565d7d5f78e20959095d430` inspected 2026-09-17. This document does not authorize merge or production.

Classification: `works`, `simulated`, `unavailable`, `blocked`, `not_run`.
Readiness: `ready_local_dry_run`, `ready_isolated_worktree`, `not_ready_staging`, `not_ready_operator`, `not_ready_public`, `blocked_live`.

No public or live-provider row is ready. Authentication, workspace isolation (open draft #211), webhook verification, mutation gates, and exact-origin CORS remain incomplete beyond private operator dry-run.

## 1. Local dry-run

Works: offline scripts on main (`deployment_smoke_check.py --local`, `mvp_readiness.py`, `local_mvp_smoke.py`, `ingest_public_signals.py --fixtures`, `check_dev_stack.py`, `run_local_quality_gate.py --from-git`). Health contract is `/health` then `/ready`.
Simulated: unit-economics assumptions, commerce MVP fixtures, CompanyOS/TrustOS packs.
Credentials: none.
Missing: this authoring sandbox had no clone; `ruff`/`docker`/`semgrep` were absent; frontend `npm test` lives on unmerged #213.
Security: artifact-store traversal still described by #211.
Persistence: JSONL under `artifacts/`. Compose Postgres/Redis are not wired by `backend/api.py`.
Rollback: stop the process; delete fixture outputs only.
Cost: $0.
Readiness: `ready_local_dry_run` on an operator checkout; `unavailable` in the inspection sandbox.

## 2. Isolated test worktree

Works: `git worktree add` against `origin/main` or one exclusive branch; `select_tests.py --from-git`.
Credentials: GitHub read.
Missing: no MarketOS checkout in the sandbox.
Security: do not share the dirty canonical Windows tree.
Rollback: `git worktree remove`.
Readiness: `ready_isolated_worktree` as process, `not_run` here.

## 3. Private staging

Works: `deploy/railway/railway.json`, `deploy/render/render.yaml`, `deploy/mvp/*`. Startup `uvicorn backend.api:app --host 0.0.0.0 --port $PORT`. Default `MARKETOS_PUBLIC_COMMERCE_RUNS=0`.
Credentials: Railway or Render (not both), exact `ALLOWED_ORIGINS`.
Missing: no operator-owned private URL observed. Netlify preview is not staging evidence.
Security: no dashboard auth on main; #211 open; previous prod compose published Postgres 5432 with password `upos` (removed in this lane); Dockerfile on main was python:3.14 root with no HEALTHCHECK (pinned to 3.12 non-root + HEALTHCHECK here).
Persistence: ephemeral JSONL unless Supabase is explicit.
Rollback: previous platform revision; unset live flags.
Readiness: `not_ready_staging`.

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

## Hardening in this lane

- Dockerfile `python:3.12-slim`, `USER marketos`, HEALTHCHECK `/health`, `STOPSIGNAL SIGINT`.
- Prod compose requires `POSTGRES_PASSWORD`, drops host 5432 publish, adds healthchecks, keeps public-run `0`.

## Sources adapted

- Docker Dockerfile reference (USER, HEALTHCHECK, STOPSIGNAL), docs.docker.com, 2026-09-17, instruction shapes only.
- FastAPI Docker deployment guide, no reload in image CMD.
- Existing MarketOS `scripts/benchmark_commerce_cycle.py` and MVP env contract; not a second quality gate.
