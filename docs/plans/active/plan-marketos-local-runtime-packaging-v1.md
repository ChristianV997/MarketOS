# Active Plan: MarketOS Local Runtime Packaging v1

Status: **active**  
Branch: `cursor/marketos-local-runtime-packaging-v1-02f1`  
Scope: local startup packaging only (no new runtime authority)

## Objective

Make one existing MarketOS local startup path reproducible without enabling live
external behavior, using the canonical Uvicorn and Docker Compose entrypoints
already documented in `README.md`.

## In scope

- `docker-compose.yml` safe defaults and optional `.env`
- `Dockerfile` / `Dockerfile.browser-use-worker` Python alignment
- `deploy/local/.env.local.example`
- `docs/LOCAL_RUNTIME_RUNBOOK.md`
- Startup packaging tests

## Out of scope

- Frontend, `scripts/ai`, event contracts, workspace isolation
- Service pilots, provider integrations, GitHub workflows
- New servers, launchers, or orchestrators

## Failure analysis

| Failure mode | Root cause | Packaging fix |
| --- | --- | --- |
| Compose fails on fresh clone | Hard-required `.env` | Optional `env_file` + inline safe defaults |
| Local smoke hits provider networks | `.env.example` enables ingestion | Dedicated offline local example + Compose defaults |
| Health vs readiness unclear | Undocumented probe semantics | Runbook + API container `/health` healthcheck |
| Container/toolchain drift | Dockerfile on Python 3.14 vs `.python-version` 3.12 | Pin images to `python:3.12-slim` |

## Verification

```bash
python -m pytest -q tests/test_local_runtime_packaging.py tests/test_deployment_config.py
python scripts/deployment_smoke_check.py --env-file deploy/local/.env.local.example --json
git diff --check
```

## Evidence handoff

Record canonical command, prerequisites, health/readiness results, changed files,
security posture, and PR URL in the agent completion report.
