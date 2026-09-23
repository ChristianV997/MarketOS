# Operator Browser Acceptance

Updated: 2026-09-21

## Purpose

Repeatable, safe operator-journey acceptance for:

- `/operator/services` (service delivery workbench)
- `/operator/first-phase` (first-phase evidence cockpit)
- `/operator/events` (operator event dashboard)

This lane owns the **browser journey harness + runner**. It does **not** replace:

- `#277` workbench producer/source-contract tests
- `#281` `scripts/ai/run_frontend_validation.py`
- `#290` `scripts/run_local_operator_stack.py`
- `#291` Shell/Sidebar responsive drawer work

## Already-approved browser tools

No new browsers, MCP servers, or Playwright installs.

| Backend | When used |
|---|---|
| **Orca embedded browser** (`orca tab` / `orca eval` / `orca screenshot` / `orca keypress`) | Preferred when `orca` is on PATH and runtime is reachable |
| **Installed Google Chrome** headless CDP (`scripts/ai/operator_browser_cdp_probe.mjs`) | Preferred fallback when Chrome and Node are installed. Dump-dom remains if CDP cannot start |
| **`--browser none`** | Deterministic HTTP + fixture contract only; **does not claim browser proof** |

Optional live UI: point at a loopback Vite server started by the `#290` local operator stack (or `npm run preview` after an existing lockfile install).

Live-UI method capture patches `fetch` **after** first paint, then exercises refresh/filter only (never the public-run POST control). Mount-time GETs may precede the patch; the fixture harness remains the strong GET-instrumentation proof.

```bash
# Fixture-only (default)
python scripts/ai/run_operator_browser_acceptance.py --json

# Prefer Orca / Chrome explicitly
python scripts/ai/run_operator_browser_acceptance.py --browser orca --json
python scripts/ai/run_operator_browser_acceptance.py --browser chrome --json

# Live local UI (read-only probe; 404 stays unavailable)
python scripts/ai/run_operator_browser_acceptance.py --live-ui http://127.0.0.1:5173 --json
```

Node contract tests (auto-picked by `npm test`):

- `frontend/tests/operator-browser-journey-acceptance.test.mjs`

Python unit tests:

- `tests/test_operator_browser_acceptance_runner.py`

## Coverage matrix

| Concern | How it is proven |
|---|---|
| Normal GET | Fixture harness fetches `/__mock_api/*` with `method: GET` |
| API down / 429 / 500 / malformed | `?api=down\|429\|500\|malformed` → surface `unavailable` (not demo-success) |
| Fixture / manual / simulated / unknown evidence | Harness rows + mock payloads include all four classes |
| Blocked / data_inadequate | Services row with `lifecycle=data_adequate` analogue `data_inadequate` |
| Filters / server order | Client filter hides rows; order note stays “Server order preserved” |
| Safe export preview | Button reveals client-safe preview text; rejects secrets language |
| Skip link | Visible skip targets per route |
| Keyboard | Orca `keypress Tab` on happy path |
| Responsive widths | Viewport matrix 375 / 768 / 1440 (+ CSS mobile/desktop classes) |
| Console / network | `__mosConsoleErrors` + `__mosRequests` via Orca `eval` |
| No POST/PUT/PATCH/DELETE | Instrumented fetch log must stay GET-only |
| No external provider action | Non-loopback URLs fail the method guard |
| SPA path on fixture server | `/operator/*` returns **404** with “not demo-success” |

## Viewport matrix

- mobile: 375×812 and 390×844
- tablet: 768×1024
- desktop: 1440×900

- `/operator/consulting-research` and `/operator/marketing-strategy` are fixture planning routes in this harness. They are not the #320/#321 React surfaces. `live_validated` and `launch_authorized` stay false.

Windows:

```powershell
powershell -File scripts/operators/Start-OperatorBrowserAcceptance.ps1 -Browser none
```

Optional local stack (#290) is not started by this script. Pass `-LiveUi http://127.0.0.1:5173` only after that stack is already listening on loopback. Artifacts stay under `%TEMP%` and are redacted before write.

Unavailable tools recorded by the runner: Orca (`orca` not on PATH), Playwright (not installed; this lane does not install it), axe (not installed). Chrome CDP is the executed browser backend when `google-chrome` and `node` exist.

## Artifacts

Screenshots and JSON reports write under the system temp dir
`%TEMP%/marketos-operator-browser-acceptance/` (or `--artifact-dir`).
**Do not commit** raw traces, screenshots, secrets, or customer data.

## Ownership / non-goals

- Do not edit `#291` Shell/Sidebar unless ownership refreshes.
- Do not edit `#271` backend producer files from this lane.
- Do not click the Operator Events “public commerce MVP” POST control during acceptance; the fixture harness omits it on purpose.
- A missing live route must remain **unavailable**, never a fabricated success.
