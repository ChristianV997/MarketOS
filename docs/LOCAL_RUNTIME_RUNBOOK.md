# MarketOS Local Runtime Runbook

This runbook documents the **existing** MarketOS local startup paths. It does not
add a new server, launcher, or deployment authority. All paths remain dry-run and
credential-free by default.

## Canonical startup commands

| Path | Command | When to use |
| --- | --- | --- |
| FastAPI API (bare metal) | `uvicorn backend.api:app --host 127.0.0.1 --port 3000` | Fastest local API smoke without Docker |
| Orchestrator spine | `python run.py` (same as `python -m orchestrator.main`) | Full phase-scheduled worker loop |
| Docker Compose API stack | `docker compose up api` | API + Redis + Qdrant with hot reload |

## Prerequisites

1. **Python 3.12** (see `.python-version`) and `pip install -r requirements.txt`.
2. Repository root as the working directory.
3. For Compose: Docker Engine with the Compose v2 plugin.
4. Optional `.env` at the repository root. When absent, Compose still starts with
   the safe inline defaults in `docker-compose.yml`. For explicit local values,
   copy `deploy/local/.env.local.example` to `.env`.

No provider credentials, API keys, or external network access are required for the
local smoke path documented here.

## Bare-metal API smoke (credential-free)

```bash
pip install -r requirements.txt
export ORCHESTRATOR_HANDLES_CYCLES=true
export SLEEP_ENABLED=0
export FF_PILLAR_A_INGESTION=false
uvicorn backend.api:app --host 127.0.0.1 --port 3000
```

Or load the committed local example:

```bash
set -a && source deploy/local/.env.local.example && set +a
uvicorn backend.api:app --host 127.0.0.1 --port 3000
```

### Health versus readiness

| Endpoint | Meaning | Expected local smoke |
| --- | --- | --- |
| `GET /health` | Process alive (liveness) | `200` with `{"ok": true, ...}` |
| `GET /ready` | Runtime services initialized (readiness) | `200` with `{"ready": true, ...}` after startup; `503` while initializing |

`/health` answers immediately. `/ready` stays `503` with
`runtime_services_initializing` until the FastAPI lifespan finishes starting
background workers.

## Docker Compose smoke (credential-free)

```bash
cp deploy/local/.env.local.example .env   # optional; inline defaults are safe
docker compose up api
```

In another terminal:

```bash
curl -fsS http://127.0.0.1:3000/health
curl -fsS http://127.0.0.1:3000/ready
```

The `api` service defines a container **liveness** healthcheck against `/health`.
Use `/ready` manually or in orchestration when you need dependency-ready semantics.

Redis must be healthy before the API container starts (`depends_on` with
`service_healthy`). Qdrant is started but not required for readiness.

## Orchestrator path

```bash
pip install -r requirements.txt
python run.py
```

This starts the full orchestrator tick loop. Discovery adapters may attempt
public network reads depending on environment flags. For offline packaging
validation, keep the research flags disabled as in `deploy/local/.env.local.example`.

## Actual versus simulated checks

| Check | Actual (local smoke) | Simulated / fixture-only |
| --- | --- | --- |
| `GET /health` | Live HTTP against running API | — |
| `GET /ready` | Live HTTP; distinguishes init vs ready | — |
| `POST /commerce/cycle` | Live HTTP with `dry_run: true` response | CI container smoke uses fixture payloads |
| `python scripts/deployment_smoke_check.py --local` | Static contract validation only | No server required |
| `python scripts/local_mvp_smoke.py` | Offline fixture path | No provider credentials |

## Security posture

- Default startup keeps commerce, ad, store, and supplier gates in dry-run mode.
- `deploy/local/.env.local.example` contains placeholders only; never commit secrets.
- Public commerce runs (`MARKETOS_PUBLIC_COMMERCE_RUNS`) and Supabase canonical
  writes remain disabled in the local example.
- Optional `.env` overrides are operator-supplied; missing `.env` does not weaken
  the default-off posture because Compose injects the same safe defaults inline.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `ModuleNotFoundError: fastapi` | Dependencies not installed | `pip install -r requirements.txt` |
| Compose fails: `.env` not found | Older Compose without optional `env_file` | Upgrade Compose v2 or `cp deploy/local/.env.local.example .env` |
| `/ready` returns `503` briefly | Normal during lifespan startup | Retry after a few seconds |
| `/ready` stays `503` with `required_medusa_unavailable` | `MEDUSA_REQUIRED_FOR_READY=true` | Unset the flag for local smoke |
| Discovery warnings in logs | Orchestrator/API tick with live adapters | Disable research flags per local example |

## Related docs

- `README.md` — Getting started overview
- `docs/MVP_DEPLOYMENT_SMOKE_CHECKS.md` — MVP deployment contract checks
- `docs/OPERATIONS.md` — Continuous orchestrator operation
