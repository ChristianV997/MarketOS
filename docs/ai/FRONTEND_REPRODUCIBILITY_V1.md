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

The validation harness never installs dependencies or accesses the network. It
reports `unavailable` when `frontend/node_modules` is absent. If dependency
provisioning is separately approved in a controlled environment, use `npm ci`
with the committed lockfile and `--ignore-scripts`; dependency lifecycle
scripts must not become an implicit execution authority. There is no `lint`
script because no supported linter configuration is committed.

The Node tests verify lockfile alignment, unsafe script markers, API base-url
sharing, bounded websocket reconnect/teardown semantics, Vite proxy coverage,
and cockpit/workbench operator-surface contracts (truthful states, no client
re-ranking, client-safe export, keyboard/live-region/table/reduced-motion
source checks). `npm test` uses `node --experimental-strip-types --test`
so TypeScript-backed workbench tests load on Node 22+ without a Windows glob
and without treating the `tests/` directory as a CJS module (Node 24). The
local quality gate allowlists `node` for that script only.

`available_read_only` is owned by PR #271's live GET wiring and is not invented
on this branch. Until that route exists, workbench compose stays
`liveEndpointUnavailable: true` and never emits `success` for fixture/manual copies.

Cockpit/workbench product files are not redesigned here. Run the same loop with:

```bash
python scripts/ai/run_frontend_validation.py --json
```

The runner classifies failures as `dependency`, `configuration`, or `source`.
It does not call Apify, Higgsfield, or other providers.

## Backend and environment boundaries

The Vite dev proxy targets `localhost:3000` for `/api`, `/ws`, and the
dashboard polling routes used by `frontend/src/lib/api.ts`. A missing backend
is an expected local condition: API helpers reject non-OK responses, React Query
surfaces the failed request, and the UI shows `reconnecting` instead of `live`.

`VITE_API_BASE_URL` and `VITE_API_URL` remain optional for direct remote API
use. `VITE_POSTHOG_KEY` is default-off.

## Evidence classification

- dependency installation: `not_run` by the validation harness
- `npm run typecheck`: real TypeScript compiler result
- `npm test`: real Node test result for the reproducibility contract
- `npm run build`: real TypeScript plus Vite production bundle result
- Browser/API behavior with a backend requires separate supervised evidence
