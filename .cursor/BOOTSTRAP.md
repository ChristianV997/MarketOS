# MarketOS Cloud Agent bootstrap

This directory configures the Cursor Cloud Agent and local contributor setup for
MarketOS.

## Policy

- **Python:** requires `ensurepip` / `python3-venv`; bootstrap scripts fail closed
  instead of installing system packages during bootstrap.
- **Frontend:** lockfile-only `npm ci --ignore-scripts --no-audit --no-fund`; no
  `npm install` fallback.
- **Network binding:** dev terminals bind to `127.0.0.1`, not `0.0.0.0`.
- **Scope:** repository-local `.venv` and `frontend/node_modules` only.
- **Secrets:** never commit `.env`, credentials, or provider tokens.

## Branch relationship

PR #214 carries the `.cursor/**` environment contract plus the merged frontend/API
reproducibility work from PR #213. GitHub currently targets `main`. Merge after both
lanes are green; do not create a second frontend authority.

## Linux / Cloud Agent install

```bash
bash .cursor/install.sh
bash .cursor/validate.sh
node --test .cursor/environment.contract.test.mjs
```

## Windows / PowerShell install

```powershell
powershell -ExecutionPolicy Bypass -File .cursor/install.ps1
bash .cursor/validate.sh
node --test .cursor/environment.contract.test.mjs
```

If Git Bash is unavailable on Windows, run the frontend validation commands manually
after `install.ps1` completes.

## Contributor validation

After bootstrap, with dependencies installed:

```bash
cd frontend
npm run typecheck
npm test
npm run build
python -m pytest -q tests/test_frontend_api_dry_run_smoke.py
```

Classify missing dependencies as `unavailable`; do not claim npm validation passed
without `frontend/node_modules`.
