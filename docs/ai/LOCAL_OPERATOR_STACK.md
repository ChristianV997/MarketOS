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

## Safety & Process Invariants

- Fixture env: `MARKETOS_MVP_MODE=1`, `MARKETOS_PUBLIC_COMMERCE_RUNS=0`, live flags off.
- Child processes receive a safe OS-runtime environment allowlist (`PATH`, `SYSTEMROOT`, `WINDIR`, `TEMP`, `TMP`, `COMSPEC`, `PATHEXT`, `APPDATA`, `LOCALAPPDATA`, `USERPROFILE`), never a copy of the operator environment. Live flags, credentials, and tokens are stripped.
- External network calls are disabled. HTTP smoke checks are loopback-only, bypass proxies, and do not follow redirects.
- Sensitive credentials, authorization headers, passwords, and API keys are regex-redacted (preserving key names, redacting secret values) and logs are capped at 8 KiB.
- Child process pipes are consumed concurrently via daemon threads to prevent OS pipe-buffer deadlocks.
- Child process groups and trees are terminated on every exit path; on Windows, `CTRL_BREAK_EVENT` is followed by tree kill (`taskkill /PID <pid> /T /F`) to eliminate grandchild processes (such as `node.exe` under `npm.cmd`).
- Verification confirms that both API and frontend loopback ports are completely free upon exit (`port_cleanup: {api_port_free, frontend_port_free}`).
- Active polling monitors child processes during `--hold`; if a process crashes during hold, the rehearsal cleanly terminates and reports `failed` with `{process}_exited_during_hold`.
- No writes to `artifacts/`, `.env`, credentials, or tracked fixtures.

## Failure Matrix Coverage (11 Scenarios)

| Scenario | Behavior / Detection | Classification |
| --- | --- | --- |
| 1. Occupied port | Detects active socket listener on API or frontend port | `blocked` with `{service}_port_occupied` |
| 2. Missing runtime | Missing Python, unimportable Uvicorn, missing Node, missing npm, missing package.json, or missing api.py | `unavailable` with `{component}_missing` / `uvicorn_not_importable` |
| 3. API fails | Non-200 / HTTP 500 error on `/health` or `/ready` | `failed` with `backend_readiness_failed` |
| 4. Frontend fails | Process crash or HTTP 500 across frontend surfaces | `failed` |
| 5. Delayed readiness | Polls `/health` with bounded retries while application initializes | Passes when ready before timeout; `timeout` if deadline exceeded |
| 6. Malformed health | `/health` returning non-JSON, empty body, or JSON with `{"ok": false}` | `failed` with `malformed_health_payload` |
| 7. Early process exit | Process terminates unexpectedly during startup or `--hold` | `failed` with `{process}_exited:{code}` or `exited_during_hold` |
| 8. Repeated invocation | Back-to-back rehearsal runs on identical ports | Passes cleanly with zero port collisions or socket leaks |
| 9. Cleanup verification | Terminated processes, dead child trees, free ports confirmed | Guaranteed in `finally:` with `port_cleanup` status |
| 10. Output redaction/caps | Credential values replaced with `[redacted]`, logs capped at 8 KiB | Verified across keys, bearer tokens, and standalone hashes |
| 11. Dry-run non-spawn | Plans commands and preflights runtime without binding or spawning | `not_run` |

## Tests

```bash
python -m pytest -q tests/test_local_operator_stack.py
```

Covers all 11 matrix scenarios: dry-run, occupied ports, missing packages/modules/executables, delayed readiness, malformed health payloads, API/frontend 500 errors, early process exit during startup and hold, repeated invocation, process tree cleanup, nonblocking pipe draining, and secret redaction.

## Rollback

Delete the three exclusive files (`scripts/run_local_operator_stack.py`, `tests/test_local_operator_stack.py`, `docs/ai/LOCAL_OPERATOR_STACK.md`) or close the draft PR. No schema migration. `start-local` print-only behavior is unchanged.
