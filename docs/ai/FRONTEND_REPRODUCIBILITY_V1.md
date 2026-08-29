# Frontend Reproducibility v1

The MarketOS dashboard is a Vite application under `frontend/` and uses npm.
`frontend/package-lock.json` is the committed dependency authority for local
and hosted installs. Do not replace it with a different package manager or
upgrade ranges casually.

## Deterministic local loop

From the repository root:

```text
cd frontend
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
npm test
npm run build
```

`npm ci` must be used for a clean locked install. `--ignore-scripts` prevents
dependency lifecycle scripts from becoming an implicit execution or network
authority. The frontend does not add a lint command because no supported
linter configuration is committed.

The `typecheck`, `test`, and `build` scripts are local and deterministic. The
Node built-in test checks package/lockfile alignment, rejects unsafe package
script markers, and verifies that API helpers surface non-OK responses when
the backend is absent. It does not start a server, call a provider, or mutate
an external system.

## Backend and environment boundaries

The Vite dev proxy targets the local backend at `localhost:3000`. A missing
backend is an expected local condition: API helpers reject non-OK responses,
React Query surfaces the failed request to the existing UI, and no fallback
claims that data was loaded. The frontend build does not require the backend
to be running.

`VITE_API_URL` and `VITE_API_BASE_URL` remain optional. `VITE_POSTHOG_KEY` is
default-off; do not provide it during offline build verification. No frontend
test or package script enables provider calls, payments, orders, advertising,
deployment, or publishing.

## Evidence classification

- `npm ci`: real local dependency installation from the committed lockfile.
- `npm run typecheck`: real TypeScript compiler result.
- `npm test`: real Node test result for the reproducibility contract.
- `npm run build`: real TypeScript plus Vite production bundle result.
- Browser/API behavior with a backend is not claimed by these commands.
- A deployed frontend or a live provider integration requires a separate
  human-reviewed environment and evidence handoff.
