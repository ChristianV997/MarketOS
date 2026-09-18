# Private staging acceptance (MarketOS API / frontend)

Default mode is **not_run**. This routine does not treat Netlify preview status as
backend, CORS, or security evidence.

## Default (no network)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\operators\Invoke-StagingAcceptance.ps1
```

Exit `0` with `evidence_class: not_run`.

## Manual private staging (human-approved URL)

When a private Railway/Render API origin exists, an operator may later probe only:

- `GET /health`
- `GET /ready`

Do **not** enable `MARKETOS_PUBLIC_COMMERCE_RUNS`, workers, or live commerce flags.
Do **not** pass provider secrets into `VITE_*`.

Frontend build (local, not a preview badge):

```powershell
Set-Location -LiteralPath '.\frontend'
npm ci --ignore-scripts --no-audit --no-fund
npm test
npm run typecheck
npm run build
```

API base: `VITE_API_BASE_URL` only, documented in PR #213. WebSocket reconnect
behavior is owned by that same frontend/API boundary — this lane does not fork it.

## Cockpit states (PR #230)

When the cockpit is present, confirm by browser (manual):

| State | Expectation |
|-------|-------------|
| loading | status region, no ranking invention |
| empty | empty ranked list copy |
| blocked | hard blockers visible |
| unavailable | endpoint failure banner |
| stale | degraded/freshness warning |
| partial | incomplete stages labeled |
| success | server-order table |

Keyboard: skip link, arrow/Home/End, Enter moves focus to detail.
Mobile: card list below `md`. Export: client-safe JSON, secret-shaped rejected.

Browser automation in this lane: **not_run** (no Playwright dependency added).

## CORS

`ALLOWED_ORIGINS` must be an exact frontend origin. Wildcard CORS is not an
acceptance pass. Inspect `deploy/mvp/env.contract.json` and
`python scripts/deployment_smoke_check.py --json` in the deployment environment.
