# Frontend/API dry-run safety contract

This contract binds the `grok/marketos-frontend-api-dry-run-smoke-v1` smoke.

## Posture

- Offline and deterministic
- Fail-closed
- No credentials required or collected
- No network provider calls
- No mutations of commerce, inventory, ads, payments, or messages
- No second protocol or runtime

## Allowed

- FastAPI `TestClient` against the existing `backend.api.app`
- Inert thread stubs so lifespan cannot start background runners
- Read `GET` routes: `/health`, `/ready`, `/api/phase1/readiness`,
  `/api/events/readiness`, `/api/cockpit/actions/{id}`
- Rejected malformed `GET` / disallowed `POST` against read views
- WebSocket connect to the existing `/ws` route with a stubbed replay payload
- Static reads of existing frontend source and `package.json`
- Optional `npm run build` if `frontend/node_modules` already exists

## Forbidden

- Creating another API app or WebSocket path
- Installing Node or Python packages as part of the smoke
- Browser automation
- Provider SDKs, paid runtimes, or CoderOS as a MarketOS dependency
- Advertising, payment, order, fulfillment, or customer-message activation
- Printing secrets, `.env` contents, or raw provider payloads
- Claiming a frontend pass when dependencies are absent

## Error rule

Safe errors may include a status code, a stable reason token, and a path.
They must not include API keys, emails used as credentials, bearer tokens,
or raw exception secrets. The smoke injects a fake secret into the process
environment and asserts it never appears in responses.

## Frontend unavailable rule

When the backend is down, the existing UI must not invent live state:

- `PhaseHeader` shows `reconnecting` rather than `live`
- `useWebSocket` reconnects with backoff and ignores malformed frames
- `canonicalEventsApi` throws `Unable to load operator events (<status>)`
- `api.ts` throws `<status> <path>` and does not echo response bodies
