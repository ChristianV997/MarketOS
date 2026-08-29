# MarketOS dashboard reproducibility (v1)

The MarketOS dashboard is a Vite application under `frontend/` and uses npm.
`frontend/package-lock.json` is the committed dependency authority.

## Deterministic local loop

```bash
cd frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
npm test
npm run build
```

`npm ci` must be used for a clean locked install. `--ignore-scripts` prevents
dependency lifecycle scripts from becoming an implicit execution authority.
There is no `lint` script because no supported linter configuration is
committed.

The Node tests verify lockfile alignment, unsafe script markers, API base-url
sharing, websocket reconnect semantics, and Vite proxy coverage. They do not
start a server or call a provider.

## Backend and environment boundaries

The Vite dev proxy targets `localhost:3000` for `/api`, `/ws`, and the
dashboard polling routes used by `frontend/src/lib/api.ts`. A missing backend
is an expected local condition: API helpers reject non-OK responses, React Query
surfaces the failed request, and the UI shows `reconnecting` instead of `live`.

`VITE_API_BASE_URL` and `VITE_API_URL` remain optional for direct remote API
use. `VITE_POSTHOG_KEY` is default-off.

## Evidence classification

- `npm ci`: real local dependency installation from the committed lockfile
- `npm run typecheck`: real TypeScript compiler result
- `npm test`: real Node test result for the reproducibility contract
- `npm run build`: real TypeScript plus Vite production bundle result
- Browser/API behavior with a backend requires separate supervised evidence
