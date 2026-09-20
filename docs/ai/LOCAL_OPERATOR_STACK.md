# Local operator stack rehearsal

Lane: `LOCAL-FULL-STACK-OPERATOR-REHEARSAL-B`
Schema: `MarketOS.LocalOperatorStack.v1`
Mode: fixture-only developer/runtime orchestration. Not a production platform.

## Why this exists

`scripts/operators/windows_operator_workflow.py start-local` **prints** the
uvicorn and Vite commands and does not spawn processes. That contract stays
unchanged (`evidence_class=not_run`).

Nothing on main chained those existing entrypoints into a bounded, offline,
cleanup-safe rehearsal that API integration and a Cursor browser pass can
reuse. This lane adds that runner only.

## One command

From a disposable worktree of this branch:

```bash
python scripts/run_local_operator_stack.py --json
```

Starts fixture-only backend + frontend, smokes the real GET surfaces, shuts
everything down, prints one JSON report.

Hold the stack for a Cursor browser pass:

```bash
python scripts/run_local_operator_stack.py --json --hold 60
```

`--hold` is capped at 300 seconds; larger values are rejected before any
process is started. Bind addresses are restricted to `localhost` or loopback
IP addresses, and startup/request timeouts are bounded.

Plan only (no processes):

```bash
python scripts/run_local_operator_stack.py --dry-run --json
```

## Ports and routes

| Plane | Default | Surfaces probed |
| --- | --- | --- |
| API | `127.0.0.1:3000` | `GET /health`, `GET /ready`, `GET /api/service-delivery/workbench` |
| Frontend | `127.0.0.1:5173` | `GET /operator/services`, `GET /operator/first-phase`, `GET /operator/events` |

Port 3000 matches `frontend/vite.config.ts` (`BACKEND_TARGET`). The Windows
`start-local` printout still documents port 8000; override with `--api-port`
if that is the operator habit.

`GET /api/service-delivery/workbench` is owned by PR #271 and is **not** on
main. A 404 is classified `surface_absent`, never as fixture success.

## Sibling authorities (not edited)

| Owner | Why untouched |
| --- | --- |
| `windows_operator_workflow.py start-local` | Print-only contract and tests |
| Cursor frontend PRs #277 #281 #282 | UI / browser acceptance |
| API producer PRs #271 #275 | Workbench GET contract and projection |
| Replay PRs #274 #279 #280 | Event.replay_hash / CLI / lab |
| Quality / CI evidence #276 | Timeout and malformed evidence |
| Deployment #249 / #289 | Container and release-smoke |
| Operator dogfood #283 | Script-chain readiness, not process start |

## Cursor browser handoff

After `--hold`, open these existing routes. Do not add a second UI suite.

```
http://127.0.0.1:5173/operator/services
http://127.0.0.1:5173/operator/first-phase
http://127.0.0.1:5173/operator/events
```

## Safety

- Fixture env: `MARKETOS_MVP_MODE=1`, `MARKETOS_PUBLIC_COMMERCE_RUNS=0`, live flags off.
- Child processes receive a small OS-runtime environment allowlist, not a copy
  of the operator environment. Fixture origins and cycle limits are fixed.
- External network calls are disabled. HTTP smoke checks are loopback-only,
  bypass proxies, and do not follow redirects.
- Logs are regex-redacted and capped at 8 KiB.
- Child process groups are stopped on every exit path; Windows uses a control
  event followed by bounded process-tree termination when necessary.
- No writes to `artifacts/`, `.env`, credentials, or tracked fixtures.
- Missing uvicorn/npm/package.json reports `unavailable`.

## Tests

```bash
python -m pytest -q tests/test_local_operator_stack.py
```

Covers dry-run, occupied ports, missing package/module, delayed readiness /
timeout, backend unavailable, frontend process exit, log redaction/caps,
404-as-surface_absent, and successful dummy-server startup + cleanup.

## Rollback

Delete the four exclusive files or close the draft PR. No schema migration.
`start-local` behavior is unchanged.
