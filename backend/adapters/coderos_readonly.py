"""backend.adapters.coderos_readonly -- thin, read-only, local-first
CoderOS capability adapter.

CoderOS is a separate, frozen control plane. This adapter does not copy,
reimplement, or replace any CoderOS orchestration -- it is a bounded,
plan-only-by-default bridge that, only when explicitly opted into, invokes
CoderOS's own local CLI surface as an argv list (never a shell string) to
read its declared capability manifest for MarketOS planning purposes.

No equivalent adapter exists anywhere in this repository (confirmed by a
repo-wide `git grep -i coderos` across *.py/*.md returning zero matches
before this file was added). This is the first CoderOS-facing surface in
MarketOS.

This module has no verified knowledge of CoderOS's actual CLI surface --
the executable name, its location relative to `coderos_root`, and the
probe subcommand are all caller-supplied configuration
(`CoderOSAdapterConfig`), not hardcoded assumptions. Nothing here
fabricates a specific CoderOS command as though it were confirmed against
CoderOS's own source; that would misrepresent provenance this adapter does
not have.

Modeled on the one existing precedent for bounded, allowlisted local CLI
invocation in this repo, `evaluation.trustos.security_ci_gate`
(existence check on the executable -> `subprocess.run([executable, *args],
cwd=root, shell=False, capture_output=True, timeout=..., check=False)` ->
byte-size cap before parsing -> JSON-decode guard -> secret-shape
rejection -- never persisting raw stdout/stderr). This file defines its
own narrow version of that pattern rather than importing TrustOS
internals, matching this repo's existing convention of each adapter
carrying its own small, self-contained safety guard (e.g.
`evaluation.commerce.dataforseo_adapter` does the same instead of sharing
a central helper).

Safety, by construction:

- `mode="plan_only"` is the default; constructing `CoderOSAdapterConfig`
  and importing this module never execute anything.
- `mode="probe"` must be requested explicitly by the caller before any
  subprocess is attempted.
- No network, credential, model, provider, SDK, or plugin call occurs
  anywhere in this file.
- `subprocess.run` is always called with an argv list (never a shell
  string), `shell=False`, a bounded `timeout`, and `capture_output=True`.
- Raw stdout/stderr are never stored on any returned dataclass -- only
  derived, whitelisted, sanitized fields.
- A parsed manifest that looks secret-shaped is rejected outright
  (`state="blocked"`), never redacted-and-kept.
- No write to CoderOS, and no artifact write, occurs anywhere in this file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "coderos-readonly-adapter-v1"
ADAPTER_VERSION = "1.0.0"

MODES = ("plan_only", "probe")
DEFAULT_MODE = "plan_only"

AVAILABILITY_STATES = ("available", "unavailable", "malformed", "timed_out", "blocked", "not_run")

DEFAULT_TIMEOUT_S = 5.0
DEFAULT_MAX_OUTPUT_BYTES = 65_536
DEFAULT_EXECUTABLE = "coderos"
# The specific subcommand is a configuration placeholder, not a verified
# CoderOS CLI contract -- see the module docstring's provenance note.
DEFAULT_PROBE_ARGS: tuple[str, ...] = ("capabilities", "--json")

_SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "access_token", "authorization", "auth_token",
    "password", "private_key", "secret", "secret_key", "token", "credential",
    "cookie", "cookies",
})
_SECRET_SHAPED_VALUE = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)


def _secret_like(value: Any) -> bool:
    """Reject (never redact-and-keep) any credential-shaped key or
    token/PEM-shaped value, recursively."""
    if isinstance(value, dict):
        for key, item in value.items():
            key_l = str(key).lower().replace("-", "_")
            if key_l in _SECRET_KEY_NAMES or _secret_like(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        return bool(_SECRET_SHAPED_VALUE.search(value))
    return False


def _now() -> float:
    return time.time()


@dataclass(frozen=True)
class CoderOSAdapterConfig:
    """Caller-supplied configuration. Constructing this dataclass never
    touches the filesystem or a subprocess -- only `probe()`, and only
    when `mode="probe"`, may do that."""

    coderos_root: str = ""
    executable: str = DEFAULT_EXECUTABLE
    probe_args: tuple[str, ...] = DEFAULT_PROBE_ARGS
    mode: str = DEFAULT_MODE
    timeout_s: float = DEFAULT_TIMEOUT_S
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unsupported CoderOS adapter mode: {self.mode}")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("max_output_bytes must be positive")

    def to_dict(self) -> dict[str, Any]:
        return {
            "coderos_root": self.coderos_root,
            "executable": self.executable,
            "probe_args": list(self.probe_args),
            "mode": self.mode,
            "timeout_s": self.timeout_s,
            "max_output_bytes": self.max_output_bytes,
        }


@dataclass(frozen=True)
class CoderOSCapabilityReference:
    """One declared CoderOS capability, extracted only from a whitelisted
    field set -- never the raw manifest entry."""

    capability_id: str
    name: str
    category: str
    read_only: bool
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "category": self.category,
            "read_only": self.read_only,
            "description": self.description,
        }


@dataclass(frozen=True)
class PlannedAction:
    """What a probe *would* do -- populated in every mode, executed only
    when `mode="probe"` is explicitly requested. Reviewable by a human
    without ever running anything."""

    executable: str
    argv: tuple[str, ...]
    working_directory: str
    timeout_s: float
    would_execute: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "executable": self.executable,
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "timeout_s": self.timeout_s,
            "would_execute": self.would_execute,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ReadOnlyProbeResult:
    """Sanitized result of a probe attempt (or its plan-only stand-in).
    Never carries raw stdout/stderr -- only a state, an exit code (when a
    process actually ran), extracted capability references, and
    warnings."""

    state: str
    exit_code: int | None
    capabilities: tuple[CoderOSCapabilityReference, ...]
    warnings: tuple[str, ...]
    duration_ms: float
    output_bytes_observed: int

    def __post_init__(self) -> None:
        if self.state not in AVAILABILITY_STATES:
            raise ValueError(f"unsupported CoderOS probe state: {self.state}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "exit_code": self.exit_code,
            "capabilities": [item.to_dict() for item in self.capabilities],
            "warnings": list(self.warnings),
            "duration_ms": self.duration_ms,
            "output_bytes_observed": self.output_bytes_observed,
        }


@dataclass(frozen=True)
class SafetySummary:
    """A structurally-enforced constant: every field must assert the safe
    value, or construction itself fails. This is not a report of what
    happened to be true this run -- it is a guarantee about this module."""

    read_only: bool
    network_calls: bool
    credentials_loaded: bool
    external_mutation: bool
    model_calls: bool
    provider_calls: bool
    sdk_used: bool
    raw_stdout_exposed: bool
    raw_stderr_exposed: bool
    artifact_writes: bool
    background_process: bool
    automatic_retry: bool
    fail_closed: bool

    def __post_init__(self) -> None:
        if not self.read_only or not self.fail_closed:
            raise ValueError("CoderOS adapter safety summary must be read_only and fail_closed")
        if any((
            self.network_calls, self.credentials_loaded, self.external_mutation,
            self.model_calls, self.provider_calls, self.sdk_used,
            self.raw_stdout_exposed, self.raw_stderr_exposed,
            self.artifact_writes, self.background_process, self.automatic_retry,
        )):
            raise ValueError("CoderOS adapter must not report any live/mutating/retaining behavior")

    def to_dict(self) -> dict[str, Any]:
        return {
            "read_only": self.read_only,
            "network_calls": self.network_calls,
            "credentials_loaded": self.credentials_loaded,
            "external_mutation": self.external_mutation,
            "model_calls": self.model_calls,
            "provider_calls": self.provider_calls,
            "sdk_used": self.sdk_used,
            "raw_stdout_exposed": self.raw_stdout_exposed,
            "raw_stderr_exposed": self.raw_stderr_exposed,
            "artifact_writes": self.artifact_writes,
            "background_process": self.background_process,
            "automatic_retry": self.automatic_retry,
            "fail_closed": self.fail_closed,
        }


def _default_safety_summary() -> SafetySummary:
    return SafetySummary(
        read_only=True, network_calls=False, credentials_loaded=False, external_mutation=False,
        model_calls=False, provider_calls=False, sdk_used=False, raw_stdout_exposed=False,
        raw_stderr_exposed=False, artifact_writes=False, background_process=False,
        automatic_retry=False, fail_closed=True,
    )


@dataclass(frozen=True)
class SanitizedAdapterReport:
    contract_version: str
    adapter_version: str
    generated_at: float
    config: dict[str, Any]
    planned_action: PlannedAction
    probe_result: ReadOnlyProbeResult
    safety_summary: SafetySummary

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "adapter_version": self.adapter_version,
            "generated_at": self.generated_at,
            "config": self.config,
            "planned_action": self.planned_action.to_dict(),
            "probe_result": self.probe_result.to_dict(),
            "safety_summary": self.safety_summary.to_dict(),
        }


def _redact_if_secret_like(value: str) -> str:
    return "[redacted]" if _secret_like(value) else value


def _sanitized_config(config: CoderOSAdapterConfig) -> dict[str, Any]:
    raw = config.to_dict()
    for key in ("coderos_root", "executable"):
        raw[key] = _redact_if_secret_like(raw[key])
    raw["probe_args"] = [_redact_if_secret_like(item) for item in raw["probe_args"]]
    return raw


def _resolve_executable(config: CoderOSAdapterConfig) -> Path:
    if os.path.isabs(config.executable):
        return Path(config.executable).resolve()
    root = Path(config.coderos_root).resolve() if config.coderos_root else Path(".").resolve()
    return (root / config.executable).resolve()


def _planned_action(config: CoderOSAdapterConfig, *, would_execute: bool, reason: str) -> PlannedAction:
    try:
        resolved_executable = str(_resolve_executable(config))
    except (OSError, ValueError):
        resolved_executable = config.executable
    executable_display = _redact_if_secret_like(resolved_executable)
    # planned_action.argv is a reviewable *display* of what would run, not
    # the actual invocation -- it must never leak a secret-shaped
    # probe_args element, even though the real subprocess call (in
    # probe(), if mode="probe") correctly uses the raw config.probe_args
    # value, since redacting the real invocation would break it.
    sanitized_probe_args = tuple(_redact_if_secret_like(arg) for arg in config.probe_args)
    return PlannedAction(
        executable=executable_display,
        argv=(executable_display, *sanitized_probe_args),
        working_directory=config.coderos_root or "",
        timeout_s=config.timeout_s,
        would_execute=would_execute,
        reason=reason,
    )


def _extract_capabilities(payload: Any) -> tuple[tuple[CoderOSCapabilityReference, ...], tuple[str, ...]]:
    if not isinstance(payload, dict):
        return (), ("manifest root must be an object",)
    entries = payload.get("capabilities")
    if not isinstance(entries, list):
        return (), ("manifest missing a 'capabilities' list",)
    capabilities: list[CoderOSCapabilityReference] = []
    warnings: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            warnings.append(f"capability_{index}_ignored_non_object")
            continue
        capability_id = entry.get("capability_id")
        name = entry.get("name")
        read_only = entry.get("read_only")
        if not isinstance(capability_id, str) or not capability_id:
            warnings.append(f"capability_{index}_missing_capability_id")
            continue
        if not isinstance(name, str) or not name:
            warnings.append(f"capability_{index}_missing_name")
            continue
        if not isinstance(read_only, bool):
            warnings.append(f"capability_{index}_missing_read_only_flag")
            continue
        category = entry.get("category")
        category = category if isinstance(category, str) and category else "unknown"
        description = entry.get("description")
        description = description if isinstance(description, str) else ""
        capabilities.append(CoderOSCapabilityReference(capability_id, name, category, read_only, description))
    return tuple(capabilities), tuple(warnings)


def _report(
    config: CoderOSAdapterConfig,
    *,
    planned: PlannedAction,
    state: str,
    exit_code: int | None = None,
    capabilities: tuple[CoderOSCapabilityReference, ...] = (),
    warnings: tuple[str, ...] = (),
    duration_ms: float = 0.0,
    output_bytes: int = 0,
) -> SanitizedAdapterReport:
    result = ReadOnlyProbeResult(state, exit_code, capabilities, warnings, duration_ms, output_bytes)
    return SanitizedAdapterReport(
        CONTRACT_VERSION, ADAPTER_VERSION, _now(), _sanitized_config(config), planned, result,
        _default_safety_summary(),
    )


def probe(config: CoderOSAdapterConfig) -> SanitizedAdapterReport:
    """Never executes anything at import or construction time -- only this
    function, and only when `config.mode == "probe"`, may invoke a
    subprocess. Every path fails closed: a missing root, missing
    executable, a path escaping `coderos_root`, oversized output, malformed
    JSON, a nonzero exit, secret-shaped output, or a timeout all resolve to
    an explicit state -- never an exception the caller must special-case,
    and never a fabricated success.
    """
    planned = _planned_action(
        config,
        would_execute=(config.mode == "probe"),
        reason="explicit probe mode requested" if config.mode == "probe"
        else "plan_only mode; explicit probe opt-in required",
    )

    if config.mode != "probe":
        return _report(config, planned=planned, state="not_run")

    if not config.coderos_root or not os.path.isdir(config.coderos_root):
        return _report(config, planned=planned, state="unavailable",
                       warnings=("coderos_root does not exist or is not a directory",))

    root = Path(config.coderos_root).resolve()
    resolved_executable = _resolve_executable(config)

    try:
        resolved_executable.relative_to(root)
    except ValueError:
        return _report(config, planned=planned, state="blocked",
                        warnings=("resolved executable escapes coderos_root",))

    if not resolved_executable.exists():
        return _report(config, planned=planned, state="unavailable",
                        warnings=("executable not found",))

    argv = [str(resolved_executable), *config.probe_args]
    start = _now()
    try:
        completed = subprocess.run(
            argv, cwd=str(root), shell=False, capture_output=True,
            timeout=config.timeout_s, text=True, check=False,
        )
    except subprocess.TimeoutExpired:
        return _report(config, planned=planned, state="timed_out",
                        warnings=("probe exceeded the bounded timeout",),
                        duration_ms=(_now() - start) * 1000)
    except OSError:
        return _report(config, planned=planned, state="unavailable",
                        warnings=("probe could not be started",),
                        duration_ms=(_now() - start) * 1000)

    duration_ms = (_now() - start) * 1000
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    output_bytes = len(stdout.encode("utf-8", errors="replace")) + len(stderr.encode("utf-8", errors="replace"))

    if output_bytes > config.max_output_bytes:
        return _report(config, planned=planned, state="malformed", exit_code=completed.returncode,
                        warnings=("probe output exceeded the byte cap; discarded",),
                        duration_ms=duration_ms, output_bytes=output_bytes)

    if completed.returncode != 0:
        return _report(config, planned=planned, state="blocked", exit_code=completed.returncode,
                        warnings=("probe exited non-zero; output discarded",),
                        duration_ms=duration_ms, output_bytes=output_bytes)

    try:
        payload = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        return _report(config, planned=planned, state="malformed", exit_code=completed.returncode,
                        warnings=("probe output was not valid JSON; discarded",),
                        duration_ms=duration_ms, output_bytes=output_bytes)

    if _secret_like(payload):
        return _report(config, planned=planned, state="blocked", exit_code=completed.returncode,
                        warnings=("probe output looked secret-shaped; rejected without persistence",),
                        duration_ms=duration_ms, output_bytes=output_bytes)

    capabilities, warnings = _extract_capabilities(payload)
    return _report(config, planned=planned, state="available", exit_code=completed.returncode,
                    capabilities=capabilities, warnings=warnings,
                    duration_ms=duration_ms, output_bytes=output_bytes)


def health() -> dict[str, Any]:
    """Offline-only readiness summary -- never touches the filesystem or a
    subprocess."""
    return {
        "name": "coderos_readonly",
        "configured": True,
        "reachable": False,
        "capabilities": ("plan_only", "bounded_local_probe"),
        "detail": "Plan-only by default; a local probe requires explicit mode='probe' opt-in.",
    }


__all__ = [
    "CONTRACT_VERSION",
    "ADAPTER_VERSION",
    "MODES",
    "DEFAULT_MODE",
    "AVAILABILITY_STATES",
    "CoderOSAdapterConfig",
    "CoderOSCapabilityReference",
    "PlannedAction",
    "ReadOnlyProbeResult",
    "SafetySummary",
    "SanitizedAdapterReport",
    "probe",
    "health",
]
