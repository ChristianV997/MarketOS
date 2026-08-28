# Frontend/API dry-run smoke runbook

Supervised, offline, fail-closed. Do not install Node or Python packages on a
Windows host from this runbook. Do not enable live providers.

## What this smoke proves

- `GET /health` returns `{ok: true}` without secrets
- `GET /ready` returns ready or a structured 503 without secrets
- `GET /api/phase1/readiness` and `GET /api/events/readiness` stay read-only
- malformed event `source` / `limit` values are rejected
- write methods against the readiness read view are rejected
- `/ws` accepts a connection and can replay a typed envelope
- frontend source encodes reconnect + backend-unavailable copy
- frontend package manager checks are real or explicitly `unavailable`

## Commands

From the repository root, with the existing Python environment:

```bash
python -m compileall -q tests/test_frontend_api_dry_run_smoke.py
python -m pytest -q tests/test_frontend_api_dry_run_smoke.py tests/test_cockpit_api.py
```

Frontend package checks (only when dependencies already exist locally):

```bash
cd frontend
npm run build
```

If `frontend/node_modules` is missing, record:

`unavailable: frontend Node dependencies are not installed; no npm install was attempted`

There is no `npm run lint` script in `frontend/package.json`. Record lint as
`unavailable: frontend/package.json has no lint script`.

## Safety stops

- Do not set live confirmation flags
- Do not call `/commerce/cycle` with live confirmation
- Do not POST `/api/cockpit/**/execute` from this smoke
- Do not start Playwright, Stripe, Shopify mutation, ads, or messaging
- Do not read or print `.env` values

## Next supervised action

Review the PR. Run the focused pytest on a machine that already has the
MarketOS Python test extra. Run `npm run build` only in an existing frontend
install. Do not merge from this agent.
