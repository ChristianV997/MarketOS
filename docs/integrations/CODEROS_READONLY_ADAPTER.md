# CoderOS read-only capability adapter (v1)

This is the first CoderOS-facing surface anywhere in MarketOS. A repo-wide
search (`git grep -i coderos` across `*.py`/`*.md`) returned zero matches
before this file existed — there is no prior adapter, no prior integration,
and no existing authority to duplicate.

CoderOS is a separate, frozen control plane. This adapter does not copy,
reimplement, or replace any CoderOS orchestration. It is a bounded,
plan-only-by-default bridge that, only when explicitly opted into, invokes
CoderOS's own local CLI surface (as configuration the caller supplies) to
read a declared capability manifest for MarketOS planning purposes.

## Provenance note

This module has **no verified knowledge of CoderOS's actual CLI surface**.
The executable name, its location relative to `coderos_root`, and the
probe subcommand are all caller-supplied configuration
(`CoderOSAdapterConfig`), not hardcoded assumptions about a real CoderOS
binary. `DEFAULT_EXECUTABLE`/`DEFAULT_PROBE_ARGS` are configuration
placeholders, not a confirmed CoderOS command — nothing in this file
claims otherwise.

## Design precedent

Modeled on the one existing precedent for bounded, allowlisted local CLI
invocation in this repository, `evaluation.trustos.security_ci_gate`
(existence check on the executable → `subprocess.run([executable, *args],
cwd=root, shell=False, capture_output=True, timeout=..., check=False)` →
byte-size cap before parsing → JSON-decode guard → secret-shape rejection
— never persisting raw stdout/stderr). This adapter defines its own small,
self-contained version of that pattern rather than importing TrustOS
internals, matching this repo's convention of each adapter carrying its
own guard (e.g. `evaluation.commerce.dataforseo_adapter` does the same
independently).

## Capability contract

Seven typed dataclasses, all in `backend/adapters/coderos_readonly.py`:

- `CoderOSAdapterConfig` — `coderos_root`, `executable`, `probe_args`,
  `mode` (`"plan_only"` default, or `"probe"`), `timeout_s`,
  `max_output_bytes`. Constructing this never touches the filesystem or a
  subprocess.
- `CoderOSCapabilityReference` — one declared capability, extracted only
  from a whitelisted field set (`capability_id`, `name`, `category`,
  `read_only`, `description`) — never the raw manifest entry.
- `PlannedAction` — what a probe *would* do (executable, argv, working
  directory, timeout, would_execute, reason), populated in every mode,
  executed only when `mode="probe"`.
- `ReadOnlyProbeResult` — `state` (one of `AVAILABILITY_STATES`), exit
  code, extracted capabilities, warnings, duration, observed output size.
  Never carries raw stdout/stderr.
- `SafetySummary` — a structurally-enforced constant: construction itself
  raises `ValueError` if any field asserts an unsafe value.
- `SanitizedAdapterReport` — wraps contract/adapter version, generated-at
  timestamp, sanitized config, the planned action, the probe result, and
  the safety summary.

## Availability states

`AVAILABILITY_STATES = ("available", "unavailable", "malformed",
"timed_out", "blocked", "not_run")`

| State | Meaning |
|---|---|
| `not_run` | `mode="plan_only"` (the default) — no subprocess attempted |
| `available` | Probe ran, exit 0, output parsed as valid non-secret-shaped JSON |
| `unavailable` | `coderos_root` missing, or the executable was not found, or the process could not start |
| `blocked` | Resolved executable escaped `coderos_root`, or exit code was non-zero, or output looked secret-shaped |
| `malformed` | Output exceeded the byte cap, or was not valid JSON |
| `timed_out` | The bounded timeout was exceeded |

## Safety behavior

- `mode="plan_only"` is the default. Constructing `CoderOSAdapterConfig`
  and importing this module never execute anything — verified by
  `test_import_time_performs_no_subprocess_call` and
  `test_constructing_config_alone_never_calls_subprocess`.
- `mode="probe"` must be requested explicitly.
- `subprocess.run` is always called with an argv **list** (never a shell
  string), `shell=False`, a bounded `timeout`, and `capture_output=True`.
- A path-traversal guard rejects any resolved executable that escapes
  `coderos_root` (unless the caller supplied an absolute path explicitly —
  their own decision, not a silent escape).
- Output is capped at `max_output_bytes`; anything larger is discarded
  (`state="malformed"`), never partially parsed.
- Any parsed manifest field that looks secret-shaped (credential-named
  keys, PEM/token-shaped values) is rejected outright (`state="blocked"`),
  never redacted-and-kept.
- Raw stdout/stderr are **never** stored on any returned dataclass — only
  derived, whitelisted fields.
- No network, credential, model, provider, SDK, plugin, or external
  service call occurs anywhere in this file (verified by an AST-based
  import check and an AST-based environment-access check in the test
  suite).
- No filesystem write or delete call exists anywhere in this file
  (verified by an AST-based check in the test suite).
- No automatic retry loop exists anywhere in this file.

## Non-goals

This is not a second provider registry, model router, orchestrator,
scheduler, queue, evidence engine, or approval system. It does not modify,
write to, or execute any mutating CoderOS operation. It does not grant
CoderOS any execution authority over MarketOS, or vice versa.

## Tests

`tests/test_coderos_readonly_adapter.py` (29 tests): plan-only default,
explicit probe opt-in, correct argv construction (both mocked and one
genuine end-to-end real-subprocess run), `shell=False`, timeout, oversized
output, missing CoderOS root, missing executable, path-traversal escape,
malformed JSON, non-zero exit, secret-shaped output rejection, sanitized
capability extraction (including skipping incomplete entries), no raw
stdout/stderr in any result, full safety-contract assertions, no
network/SDK imports, no environment-variable access, no filesystem
write/delete calls, no import-time or construction-time execution,
deterministic output, and config validation.
