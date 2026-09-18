# Frontend/API dry-run smoke runbook

Supervised, offline, fail-closed. Do not enable live providers, payments, ads,
orders, or browser automation from this runbook.

## What this smoke proves

- `GET /health` returns `{ok: true}` without secrets
- `GET /ready` distinguishes runtime initialization from liveness
- `GET /api/phase1/readiness` and `GET /api/events/readiness` stay read-only
- `GET /api/events/timeline` is safe without credentials
- malformed event `source` / `limit` values are rejected
- write methods against readiness read views are rejected
- `POST /commerce/cycle` remains `dry_run: true`
- `/ws` accepts a connection and can replay a typed envelope
- frontend lockfile, typecheck, tests, and build are reproducible
- frontend source encodes reconnect + backend-unavailable copy

## Commands

From the repository root, with the existing Python environment:

```bash
python -m compileall -q tests/test_frontend_api_dry_run_smoke.py
python -m pytest -q tests/test_frontend_api_dry_run_smoke.py tests/test_cockpit_api.py tests/test_commerce_api.py::test_readiness_distinguishes_health_from_runtime_startup
```

Frontend package checks:

```bash
cd frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
npm test
npm run build
```

Lint: `unavailable` — `frontend/package.json` has no `lint` script.

## Local dev without env vars

With the backend on `localhost:3000` and the Vite dev server on `5173`, the
committed `vite.config.ts` proxy forwards:

- `/api/*`
- `/ws`
- dashboard polling routes at the backend root (`/metrics`, `/snapshot`, ...)

Set `VITE_API_BASE_URL` or `VITE_API_URL` only when the frontend must call a
remote backend directly.

## Safety stops

- Do not set live confirmation flags
- Do not POST `/api/cockpit/**/execute` from this smoke
- Do not start Playwright, Stripe, Shopify mutation, ads, or messaging
- Do not read or print `.env` values
