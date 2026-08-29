# Active Plan: MarketOS Frontend Reproducibility v1

- **Plan ID:** `plan-marketos-frontend-reproducibility-v1`
- **Task:** Make the existing React/Vite frontend reproducible for supervised local development.
- **Branch:** `gpt/marketos-frontend-reproducibility-v1`
- **Lane:** `jules`
- **Status:** `active`

## Objective

Use the repository’s existing npm/Vite/TypeScript setup as one deterministic
frontend toolchain. Lock the declared dependency graph, expose standalone
typecheck and local test commands, and document the missing-backend and
provider-offline boundaries without changing application behavior.

## Scope

```json
{
  "in_scope": [
    "frontend/package.json scripts",
    "frontend/package-lock.json generated from the existing package manifest",
    "frontend/tests/reproducibility.test.mjs",
    "frontend typecheck/build/install documentation",
    "frontend local quality evidence"
  ],
  "out_of_scope": [
    "frontend application behavior and UI",
    "backend, services, events, workspaces, and providers",
    "scripts/ai quality gate and GitHub workflows",
    "browser automation, deployment, publishing, payment, orders, or advertising",
    "dependency range upgrades unrelated to lockfile creation"
  ]
}
```

## Target Files

- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/tests/reproducibility.test.mjs`
- `docs/ai/FRONTEND_REPRODUCIBILITY_V1.md`
- `docs/plans/active/plan-marketos-frontend-reproducibility-v1.md`

## Interface Contracts

- npm consumes `frontend/package.json` and `frontend/package-lock.json` through
  `npm ci`, `npm run typecheck`, `npm test`, and `npm run build`.
- The Node test consumes the package manifest, lockfile, and existing frontend
  API source as read-only inputs.
- Vite consumes the existing TypeScript and Vite configuration; no backend
  process is required for a production build.

## Evidence and acceptance

- npm is the intended manager because README, Vercel, and existing scripts use
  npm and no competing lockfile exists.
- `npm ci --ignore-scripts --no-audit --no-fund` installs the committed graph.
- `npm run typecheck`, `npm test`, and `npm run build` pass locally.
- API helpers preserve explicit non-OK rejection when the backend is absent.
- Package scripts contain no install, network, provider, publish, or deployment
  command, and no application files are changed.

## Risk

```json
{
  "level": "LOW",
  "mitigation": "Only the npm lockfile, package scripts, a dependency-free test, and documentation are changed. npm lifecycle scripts are disabled during verification; application, backend, provider, and deployment code remain untouched."
}
```

## Ownership

The frontend lane owns the package manifest, its committed npm lockfile, the
focused reproducibility test, and the accompanying operator documentation.
Backend, service, event, workspace, provider, CoderOS, and CI authorities remain
owned by their existing lanes and are not modified by this plan.

## Verification commands

- `npm ci --ignore-scripts --no-audit --no-fund`
- `npm run typecheck`
- `npm test`
- `npm run build`
- `python -m pytest -q tests/test_ai_dev_stack.py tests/test_agentic_operating_layer.py` (adjacent repository checks)
- `git diff --check`

## Stop conditions

Stop if the lockfile requires an unreviewed dependency upgrade, the package
manager is ambiguous, frontend application behavior must change, a provider or
network call is needed, a workflow/backend/CoderOS file enters the diff, or
the clean install/typecheck/build cannot be reproduced.
