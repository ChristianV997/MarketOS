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
- **Line endings:** `.cursor/*.sh` must stay LF. CRLF breaks bash `set -o pipefail`
  on Windows (`pipefail\r: invalid option name`). `.gitattributes` enforces LF on
  checkout; Windows contributors must use the PowerShell bootstrap path below.

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
powershell -ExecutionPolicy Bypass -File .cursor/validate.ps1
node --test .cursor/environment.contract.test.mjs
```

`install.ps1` runs `validate.ps1` automatically. Do not run `bash .cursor/validate.sh`
on Windows unless Git Bash is configured for LF checkouts; CRLF working-tree copies
break bash before any script logic runs.

If shell scripts were checked out with CRLF, renormalize and retry:

```powershell
git add --renormalize .cursor
git status
```

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
