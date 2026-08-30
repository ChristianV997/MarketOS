# MarketOS Cloud Agent bootstrap

This directory configures the Cursor Cloud Agent environment for MarketOS.

## Policy

- **Python:** requires an image with `ensurepip` / `python3-venv`; `install.sh` fails
  closed instead of running `sudo apt-get`.
- **Frontend:** lockfile-only `npm ci --ignore-scripts --no-audit --no-fund`; no
  `npm install` fallback.
- **Network binding:** dev terminals bind to `127.0.0.1`, not `0.0.0.0`.
- **Scope:** repository-local `.venv` and `frontend/node_modules` only.

## Stack relationship

PR #214 is stacked on PR #213 (`codex/marketos-frontend-api-boundary-v5`), not on
`main`. Merge #213 first, then rebase or retarget #214 before merging it.

## Validation

After `bash .cursor/install.sh`:

```bash
cd frontend
npm run typecheck
npm test
npm run build
```
