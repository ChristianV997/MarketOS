# Canonical Paths

Updated: 2026-09-18

| Concern | Inspect first |
|---|---|
| Financial calculations and money | `backend/economics/kernel.py` |
| Event spine & envelope | `backend/contracts/events.py` |
| Replay certification & identity | `backend/events/replay_certification.py` |
| Client export & isolation boundary | `evaluation/trustos/client_workspace_isolation.py` |
| Resource execution governance | `evaluation/companyos/resource_execution_governor.py` |
| Pre-integration policy gate & approval | `evaluation/companyos/approval_ledger.py` |
| Opportunity synthesis (3 pillars) | `evaluation/commerce/opportunity_synthesis.py` |
| Service projection contracts | `evaluation/companyos/service_delivery_artifact.py`, `evaluation/companyos/service_engagement.py` |
| Frontend API client & base URL | `frontend/src/lib/apiBase.ts` |
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
