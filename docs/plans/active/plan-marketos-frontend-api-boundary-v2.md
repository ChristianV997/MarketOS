# Active Plan: MarketOS Frontend/API Boundary v3

- **Plan ID:** `plan-marketos-frontend-api-boundary-v3`
- **Branch:** `cursor/marketos-frontend-api-boundary-v3-02f1`
- **Supersedes:** closed PR #203 (`cursor/marketos-frontend-api-boundary-v2`)
- **Lane:** `frontend_api_boundary`
- **Owner:** frontend/API boundary engineer
- **Status:** `active`
- **Base:** `main` @ `f0cfdb83487306ea434d50cdd1dcc8280134815e`

## Objective

Make local frontend development reproducible for CoderOS-assisted work and add
focused boundary tests for the existing API, readiness, canonical-events,
cockpit, and WebSocket surfaces without creating a second runtime.

## Risk

```json
{
  "level": "LOW",
  "mitigation": "Limit changes to frontend package metadata, lib clients, Vite proxy coverage, boundary tests, and documentation. Keep dry-run defaults and zero-spend posture unchanged."
}
```

## Stop conditions

- Stop if a change requires backend event-spine, workspace, provider, or workflow edits.
- Stop if npm install would need network activation beyond the committed lockfile during smoke.
- Stop if tests cannot distinguish unavailable from passed.
- Stop if scope expands beyond the exclusive file list.

## Target files

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.ts`
- `frontend/src/lib/apiBase.ts`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/canonicalEventsApi.ts`
- `frontend/tests/*.test.mjs`
- `tests/test_frontend_api_dry_run_smoke.py`
- `docs/FRONTEND_API_DRY_RUN_SMOKE_RUNBOOK.md`
- `docs/FRONTEND_API_DRY_RUN_SAFETY_CONTRACT.md`
- `docs/ai/FRONTEND_REPRODUCIBILITY_V1.md`
- `docs/plans/active/plan-marketos-frontend-api-boundary-v2.md`

## Interface contracts

| Surface | Contract |
| --- | --- |
| `resolveApiBaseUrl()` | `VITE_API_BASE_URL` → `VITE_API_URL` → `""` |
| `api.ts` | non-OK HTTP throws `` `${status} ${path}` `` |
| `canonicalEventsApi.ts` | non-OK HTTP throws `Unable to load operator events (<status>)` |
| `useWebSocket.ts` | reconnect backoff; malformed frames ignored |
| `PhaseHeader.tsx` | disconnected state shows `reconnecting`, not `live` |
| `/health` | liveness only |
| `/ready` | readiness; may return `503` while initializing |
| `/api/events/*` | read-only without credentials in smoke |
| `/api/cockpit/actions/{id}` | missing action returns `not_found` |

## Verification commands

```bash
cd frontend && npm ci --ignore-scripts --no-audit --no-fund && npm run typecheck && npm test && npm run build
python -m compileall tests/test_frontend_api_dry_run_smoke.py
python -m pytest -q tests/test_frontend_api_dry_run_smoke.py tests/test_cockpit_api.py
git diff --check
```

## Acceptance criteria

- [x] Committed npm lockfile matches `package.json`
- [x] `typecheck`, `test`, and `build` scripts exist and pass locally
- [x] Vite dev proxy covers dashboard polling routes without env vars
- [x] API clients share base-url resolution
- [x] Dry-run smoke covers health, readiness, canonical events, cockpit, websocket, and commerce dry-run
- [x] Unavailable lint is documented, not faked
- [x] No provider, payment, order, or network activation introduced

## Recovery conditions

- If frontend build fails after lockfile refresh: regenerate lockfile from the existing manifest only; do not upgrade ranges casually.
- If API smoke fails on envelope semantics: repair within `tests/test_frontend_api_dry_run_smoke.py` and allowed frontend lib files only.
- If proxy coverage regresses: extend `vite.config.ts` root-route regex rather than adding a second API client.

## Out of scope

- Backend production code, event spine, workspace isolation, providers, CoderOS
- `scripts/ai/run_local_quality_gate.py`
- GitHub workflows, Docker, credentials, secrets
- New API/WebSocket servers or orchestration loops
