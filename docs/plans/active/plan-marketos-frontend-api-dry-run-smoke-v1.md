# Plan: MarketOS frontend/API dry-run smoke v1

Status: active, supervised, unmerged
Owner: frontend/API boundary engineer
Branch: `grok/marketos-frontend-api-dry-run-smoke-v1`
Base: `main` @ `f0cfdb83487306ea434d50cdd1dcc8280134815e`

## Goal

Improve the supervised developer experience around the existing React/Vite
frontend and FastAPI/WebSocket boundary by proving the boundary is alive and
fail-closed. No live external behavior is added.

## Canonical owners reused

| Concern | Owner |
| --- | --- |
| Health / readiness | `api/routes/health.py` |
| Read-only operator events | `api/routes/canonical_events.py` |
| Phase 1 readiness read view | `api/routes/phase1_readiness.py` |
| Cockpit read/preview surface | `api/routes/execution_cockpit.py` |
| WebSocket protocol | `api/ws.py` → `backend/ws/stream.py` mounted at `/ws` in `backend/api.py` |
| Frontend package | `frontend/package.json` (`npm run build` = `tsc && vite build`) |
| Frontend live stream | `frontend/src/hooks/useWebSocket.ts` |
| Frontend read client | `frontend/src/lib/api.ts`, `frontend/src/lib/canonicalEventsApi.ts` |
| Backend-unavailable UI | `frontend/src/components/PhaseHeader.tsx` (`reconnecting`) |

## In scope

- Focused Pytest + FastAPI TestClient smoke
- Static frontend package/type/unavailable-backend contracts
- Honest `unavailable` reporting when Node deps or lint scripts are absent
- One active plan, operator runbook, and dry-run safety contract

## Out of scope

- Second API or WebSocket protocol
- New orchestration loop, quality gate, event store, or workspace manager
- CoderOS runtime dependency inside MarketOS
- Provider, browser, advertising, payment, order, or customer-message activation
- Windows host installation
- Codex / GPT quality-gate / Claude event-workspace / Cursor service-pilot work
- Changes to `scripts/ai/**`, `services/**`, `backend/contracts/events.py`,
  `backend/events/**`, `backend/workspaces/**`, `evaluation/trustos/**`,
  provider integrations, `.github/workflows/**`, or CoderOS

## Validation intended

- `python -m compileall` on touched Python
- `python -m pytest -q tests/test_frontend_api_dry_run_smoke.py`
- Adjacent: `tests/test_cockpit_api.py`, `tests/test_commerce_api.py` readiness cases
- Frontend `npm run build` only when `frontend/node_modules` exists
- Frontend lint: unavailable (no `lint` script in `frontend/package.json`)
- `git diff --check` and staged secret scan before commit
