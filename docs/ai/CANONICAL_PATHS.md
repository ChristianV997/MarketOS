# Canonical Paths

Updated: 2026-07-31

| Concern | Inspect first |
|---|---|
| API and readiness | `backend/api.py`, `api/` |
| Main execution | `orchestrator/`, `execution/`, `backend/execution/` |
| Signals and ingestion | `signals/`, `backend/adapters/`, `backend/signal_cache/` |
| Product ranking/economics | `evaluation/`, `backend/validation/`, `backend/decision/` |
| Ads and publishing | `backend/integrations/`, `backend/launch/`, `backend/organic/` |
| Commerce state | `backend/commerce/`, `connectors/` |
| Metrics/alerts | `backend/observability/`, `metrics/`, `monitoring/` |
| Tests | `tests/` |
| Deployment | `.github/`, `docker-compose*.yml`, `Dockerfile*` |
| AI workflow memory | `docs/ai/` |

Do not infer ownership from filenames alone; verify imports and runtime callers.
