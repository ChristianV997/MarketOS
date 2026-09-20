#!/usr/bin/env python3
"""Fixture-only local operator-stack rehearsal.

Starts (or dry-plans) the existing MarketOS backend and frontend so API
integration and a Cursor browser pass do not depend on improvised setup.

This is developer/runtime orchestration. It does not become a second API,
frontend, event, replay, quality-gate, or readiness authority.

Safety:
    - fixture-only environment; live provider keys are stripped
    - no secrets written; logs are redacted and capped
    - processes are always cleaned up on success, failure, or interrupt
    - missing dependencies report unavailable rather than invented success
    - HTTP 404 on an unmerged producer route is surface_absent, not passed
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA = "MarketOS.LocalOperatorStack.v1"
DEFAULT_API_HOST = "127.0.0.1"
DEFAULT_API_PORT = 3000
DEFAULT_FRONTEND_HOST = "127.0.0.1"
DEFAULT_FRONTEND_PORT = 5173
DEFAULT_STARTUP_TIMEOUT_S = 30.0
DEFAULT_REQUEST_TIMEOUT_S = 2.0
DEFAULT_LOG_CAP_BYTES = 8192
MAX_STARTUP_TIMEOUT_S = 120.0
MAX_REQUEST_TIMEOUT_S = 30.0
MAX_HOLD_S = 300.0
SAFE_PROCESS_ENV_KEYS = frozenset(
    {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATHEXT",
        "APPDATA",
        "LOCALAPPDATA",
        "USERPROFILE",
    }
)
CLASSIFICATIONS = frozenset(
    {"passed", "partial", "unavailable", "blocked", "timeout", "failed", "not_run", "surface_absent"}
)

# Frontend routes already present on main (frontend/src/main.tsx).
FRONTEND_SURFACES = (
    ("workbench_ui", "/operator/services"),
    ("cockpit_ui", "/operator/first-phase"),
    ("operator_events_ui", "/operator/events"),
)

# API surfaces. Workbench producer lives on PR #271; on main a 404 is honest.
API_SURFACES = (
    ("health", "/health"),
    ("ready", "/ready"),
    ("workbench_api", "/api/service-delivery/workbench"),
)

LIVE_FLAG_KEYS = (
    "MARKETOS_ALLOW_LIVE",
    "MARKETOS_LIVE_PROVIDERS",
    "ALLOW_NETWORK",
    "MARKETOS_PUBLIC_COMMERCE_RUNS",
)
SECRET_ENV_KEYS = (
    "APIFY_API_TOKEN",
    "DATAFORSEO_LOGIN",
    "DATAFORSEO_PASSWORD",
    "SERPAPI_API_KEY",
    "SHOPIFY_ACCESS_TOKEN",
    "CJ_API_KEY",
    "CJ_EMAIL",
    "STRIPE_SECRET_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GITHUB_TOKEN",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_ANON_KEY",
)
_SECRET_PATTERNS = (
    # Key-value assignments like key: value or key=value
    re.compile(
        r'(?i)\b((?:api[_-]?key|access[_-]?token|authorization|password|secret)\s*[:=]\s*)(["\']?)([^"\'\s,;&]+)\2'
    ),
    # Bearer tokens
    re.compile(r'(?i)\b(bearer\s+)([A-Za-z0-9_\-\.+=/]+)'),
    # Standalone sk-... and ghp_...
    re.compile(r'\b(sk-(?:live|proj)-[A-Za-z0-9_\-]+|ghp_[A-Za-z0-9_\-]+)\b'),
)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep loopback smoke probes from following redirects to remote hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalOperatorStackError(Exception):
    """Bounded rehearsal failure."""


@dataclass
class StackConfig:
    repo: Path = field(default_factory=lambda: ROOT)
    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    frontend_host: str = DEFAULT_FRONTEND_HOST
    frontend_port: int = DEFAULT_FRONTEND_PORT
    startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S
    request_timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S
    log_cap_bytes: int = DEFAULT_LOG_CAP_BYTES
    hold_s: float = 0.0
    start_backend: bool = True
    start_frontend: bool = True
    # Starting services and probing loopback are opt-in. A bare invocation is
    # a plan-only report and must not bind, connect, or spawn child processes.
    dry_run: bool = True
    fixture_only: bool = True


def classify(value: str) -> str:
    if value not in CLASSIFICATIONS:
        raise LocalOperatorStackError(f"unknown classification: {value!r}")
    return value


def port_in_use(host: str, port: int) -> bool:
    """True when another process is listening (connectable) on host:port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.2)
    try:
        return sock.connect_ex((host, port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def port_bind_conflict(host: str, port: int) -> bool:
    """True when the local bind would fail (occupied or not yet reusable)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        return True
    finally:
        sock.close()
    return False


def wait_port(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        try:
            if sock.connect_ex((host, port)) == 0:
                return True
        except OSError:
            pass
        finally:
            sock.close()
        time.sleep(0.05)
    return False


def wait_port_free(host: str, port: int, timeout_s: float = 2.0) -> bool:
    """Wait until host:port is no longer in use."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not port_in_use(host, port):
            return True
        time.sleep(0.05)
    return not port_in_use(host, port)


def redact(text: str) -> str:
    if not text:
        return ""
    result = _SECRET_PATTERNS[0].sub(r'\1\2[redacted]\2', text)
    result = _SECRET_PATTERNS[1].sub(r'\1[redacted]', result)
    result = _SECRET_PATTERNS[2].sub(r'[redacted]', result)
    return result


def cap_log(text: str, cap_bytes: int) -> str:
    raw = (text or "").encode("utf-8", errors="replace")
    if len(raw) <= cap_bytes:
        return text or ""
    kept = raw[:cap_bytes].decode("utf-8", errors="replace")
    return kept + f"\n...[truncated {len(raw) - cap_bytes} bytes]"


def fixture_environ(base: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if base is None else base
    env = {
        key: value
        for key, value in source.items()
        if key.upper() in SAFE_PROCESS_ENV_KEYS and key.upper() not in SECRET_ENV_KEYS
    }
    env["MARKETOS_MVP_MODE"] = "1"
    env["MARKETOS_PUBLIC_COMMERCE_RUNS"] = "0"
    env["ORCHESTRATOR_HANDLES_CYCLES"] = "true"
    env["ALLOWED_ORIGINS"] = "http://127.0.0.1:5173"
    env["CYCLES_PER_MINUTE"] = "1"
    env["MARKETOS_ALLOW_LIVE"] = "0"
    env["MARKETOS_LIVE_PROVIDERS"] = "0"
    return env


def _is_loopback_host(host: str) -> bool:
    if not isinstance(host, str):
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.casefold() == "localhost"


def validate_stack_config(config: StackConfig) -> list[str]:
    """Reject non-local binds and unbounded ports, timeouts, or log caps."""
    errors: list[str] = []
    for field_name, host in (("api", config.api_host), ("frontend", config.frontend_host)):
        if not _is_loopback_host(host):
            errors.append(f"{field_name}_host_not_loopback")
    for field_name, port in (("api", config.api_port), ("frontend", config.frontend_port)):
        if type(port) is not int or not 1 <= port <= 65535:
            errors.append(f"{field_name}_port_out_of_range")
    for field_name, value, maximum in (
        ("startup_timeout", config.startup_timeout_s, MAX_STARTUP_TIMEOUT_S),
        ("request_timeout", config.request_timeout_s, MAX_REQUEST_TIMEOUT_S),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
            errors.append(f"{field_name}_out_of_range")
    if (
        type(config.hold_s) not in (int, float)
        or not math.isfinite(config.hold_s)
        or not 0 <= config.hold_s <= MAX_HOLD_S
    ):
        errors.append("hold_s_out_of_range")
    if type(config.log_cap_bytes) is not int or not 256 <= config.log_cap_bytes <= 65536:
        errors.append("log_cap_bytes_out_of_range")
    return errors


def backend_argv(config: StackConfig) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.api:app",
        "--host",
        config.api_host,
        "--port",
        str(config.api_port),
    ]


def frontend_argv(config: StackConfig) -> list[str]:
    npm = shutil.which("npm") or shutil.which("npm.cmd") or "npm"
    return [
        npm,
        "--prefix",
        str(config.repo / "frontend"),
        "run",
        "dev",
        "--",
        "--host",
        config.frontend_host,
        "--port",
        str(config.frontend_port),
        "--strictPort",
    ]


@dataclass
class ManagedProcess:
    name: str
    argv: list[str]
    proc: subprocess.Popen[str] | None = None
    log_cap_bytes: int = DEFAULT_LOG_CAP_BYTES
    _log_chunks: list[str] = field(default_factory=list, repr=False)
    _log_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _reader_thread: threading.Thread | None = field(default=None, repr=False)

    def _read_stream(self) -> None:
        if self.proc is None or self.proc.stdout is None:
            return
        try:
            for line in iter(self.proc.stdout.readline, ""):
                with self._log_lock:
                    self._log_chunks.append(line)
        except (OSError, ValueError):
            pass
        finally:
            try:
                if self.proc and self.proc.stdout:
                    self.proc.stdout.close()
            except (OSError, ValueError):
                pass

    def start(self, *, cwd: Path, env: Mapping[str, str]) -> None:
        try:
            process_options: dict[str, Any] = {}
            if os.name == "nt":
                process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                process_options["start_new_session"] = True
            self.proc = subprocess.Popen(
                self.argv,
                cwd=str(cwd),
                env=dict(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **process_options,
            )
            self._log_chunks.clear()
            self._reader_thread = threading.Thread(target=self._read_stream, daemon=True)
            self._reader_thread.start()
        except FileNotFoundError as exc:
            raise LocalOperatorStackError(f"{self.name}_executable_not_found:{exc}") from exc
        except OSError as exc:
            raise LocalOperatorStackError(f"{self.name}_start_failed:{exc}") from exc

    def poll(self) -> int | None:
        if self.proc is None:
            return None
        return self.proc.poll()

    def terminate(self, timeout_s: float = 2.0) -> str:
        if self.proc is None:
            return "not_started"
        pid = self.proc.pid
        if self.proc.poll() is not None:
            if os.name == "nt":
                taskkill = shutil.which("taskkill")
                if taskkill:
                    try:
                        subprocess.run(
                            [taskkill, "/PID", str(pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            check=False,
                            timeout=2.0,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        pass
            return "already_exited"

        if os.name == "nt":
            try:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            except (AttributeError, OSError, ValueError):
                try:
                    self.proc.terminate()
                except OSError:
                    pass
        else:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    self.proc.terminate()
                except OSError:
                    pass

        deadline = time.monotonic() + min(timeout_s, 1.0)
        while time.monotonic() < deadline and self.proc.poll() is None:
            time.sleep(0.05)

        if os.name == "nt":
            taskkill = shutil.which("taskkill")
            if taskkill:
                try:
                    subprocess.run(
                        [taskkill, "/PID", str(pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        timeout=2.0,
                    )
                except (OSError, subprocess.TimeoutExpired):
                    pass
        else:
            if self.proc.poll() is None:
                try:
                    os.killpg(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    pass

        if self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass

        try:
            self.proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass

        return "terminated" if self.proc.poll() is not None else "cleanup_failed"

    def drain_log(self) -> str:
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=0.5)
        with self._log_lock:
            text = "".join(self._log_chunks)
        return cap_log(redact(text), self.log_cap_bytes)


def http_get(url: str, timeout_s: float) -> dict[str, Any]:
    try:
        parsed = urllib.parse.urlsplit(url)
        parsed.port
    except ValueError:
        parsed = None
    if (
        parsed is None
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not _is_loopback_host(parsed.hostname)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or type(timeout_s) not in (int, float)
        or not math.isfinite(timeout_s)
        or not 0 < timeout_s <= MAX_REQUEST_TIMEOUT_S
    ):
        return {
            "url": "<redacted>" if parsed is not None and (parsed.username or parsed.password) else None,
            "http_status": None,
            "classification": classify("blocked"),
            "bytes": 0,
            "reason": "unsafe_or_unbounded_http_probe",
        }
    request = urllib.request.Request(url, method="GET")
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirectHandler(),
        )
        with opener.open(request, timeout=timeout_s) as response:
            body = response.read(4096)
            status = int(response.status)
            kind = "passed" if 200 <= status < 400 else "failed"
            payload_info: dict[str, Any] = {}

            # Validate health and ready responses
            path = (parsed.path or "").rstrip("/")
            if path == "/health":
                try:
                    data = json.loads(body.decode("utf-8", errors="replace"))
                    payload_info["json_valid"] = True
                    if not isinstance(data, dict) or data.get("ok") is not True:
                        kind = "failed"
                        payload_info["error"] = "malformed_health_payload"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    kind = "failed"
                    payload_info["json_valid"] = False
                    payload_info["error"] = "malformed_health_payload"
            elif path == "/ready":
                try:
                    data = json.loads(body.decode("utf-8", errors="replace"))
                    payload_info["json_valid"] = True
                    if not isinstance(data, dict) or data.get("ready") is not True:
                        kind = "failed"
                        payload_info["error"] = "malformed_ready_payload"
                except (json.JSONDecodeError, UnicodeDecodeError):
                    kind = "failed"
                    payload_info["json_valid"] = False
                    payload_info["error"] = "malformed_ready_payload"

            row: dict[str, Any] = {
                "url": url,
                "http_status": status,
                "classification": classify(kind),
                "bytes": len(body),
            }
            if payload_info:
                row["payload_validation"] = payload_info
                if "error" in payload_info and kind == "failed":
                    row["reason"] = payload_info["error"]
            return row
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if status == 404:
            kind = "surface_absent"
        elif 300 <= status < 600:
            kind = "failed"
        else:
            kind = "unavailable"
        return {"url": url, "http_status": status, "classification": classify(kind), "bytes": 0}
    except TimeoutError:
        return {"url": url, "http_status": None, "classification": classify("timeout"), "bytes": 0}
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        kind = "timeout" if "timed out" in reason.lower() else "unavailable"
        return {"url": url, "http_status": None, "classification": classify(kind), "bytes": 0, "reason": reason}
    except OSError as exc:
        return {"url": url, "http_status": None, "classification": classify("unavailable"), "bytes": 0, "reason": str(exc)}


def wait_health_ready(
    host: str,
    port: int,
    path: str,
    timeout_s: float,
    *,
    request_timeout_s: float = 1.0,
    check_process: Callable[[], int | None] | None = None,
) -> tuple[bool, str | None]:
    """Poll a health/ready endpoint until it returns passed, or times out/crashes."""
    deadline = time.monotonic() + timeout_s
    last_reason: str | None = None
    while time.monotonic() < deadline:
        if check_process:
            code = check_process()
            if code is not None:
                return False, f"process_exited:{code}"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        url = f"http://{host}:{port}{path}"
        row = http_get(url, min(request_timeout_s, max(0.1, remaining)))
        if row["classification"] == "passed":
            return True, None
        last_reason = row.get("reason") or f"http_{row.get('http_status')}"
        time.sleep(0.05)
    return False, last_reason or "readiness_timeout"


def preflight(config: StackConfig) -> dict[str, Any]:
    python_ok = bool(sys.executable)
    uvicorn_spec = True
    try:
        import importlib.util

        uvicorn_spec = importlib.util.find_spec("uvicorn") is not None
    except (ImportError, ValueError):
        uvicorn_spec = False
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    node = shutil.which("node")
    frontend_pkg = (config.repo / "frontend" / "package.json").is_file()
    api_module = (config.repo / "backend" / "api.py").is_file()
    occupied = (
        {"api": None, "frontend": None}
        if config.dry_run
        else {
            "api": port_bind_conflict(config.api_host, config.api_port),
            "frontend": port_bind_conflict(config.frontend_host, config.frontend_port),
        }
    )
    return {
        "configuration_valid": True,
        "python": python_ok,
        "uvicorn_importable": uvicorn_spec,
        "npm": bool(npm),
        "node": bool(node),
        "frontend_package_json": frontend_pkg,
        "backend_api_module": api_module,
        "occupied_ports": occupied,
    }


def smoke_surfaces(config: StackConfig, *, backend_up: bool, frontend_up: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if backend_up:
        for name, path in API_SURFACES:
            target = f"http://{config.api_host}:{config.api_port}{path}"
            row = http_get(target, config.request_timeout_s)
            row["name"] = name
            row["plane"] = "api"
            rows.append(row)
    else:
        for name, path in API_SURFACES:
            rows.append(
                {
                    "name": name,
                    "plane": "api",
                    "url": f"http://{config.api_host}:{config.api_port}{path}",
                    "http_status": None,
                    "classification": classify("unavailable"),
                    "bytes": 0,
                    "reason": "backend_not_started",
                }
            )
    if frontend_up:
        for name, path in FRONTEND_SURFACES:
            target = f"http://{config.frontend_host}:{config.frontend_port}{path}"
            row = http_get(target, config.request_timeout_s)
            row["name"] = name
            row["plane"] = "frontend"
            rows.append(row)
    else:
        for name, path in FRONTEND_SURFACES:
            rows.append(
                {
                    "name": name,
                    "plane": "frontend",
                    "url": f"http://{config.frontend_host}:{config.frontend_port}{path}",
                    "http_status": None,
                    "classification": classify("not_run"),
                    "bytes": 0,
                    "reason": "frontend_not_started",
                }
            )
    return rows


def _overall(rows: list[dict[str, Any]], *, backend_started: bool, frontend_started: bool) -> str:
    health = next((row for row in rows if row["name"] == "health"), None)
    if backend_started and health and health["classification"] == "passed":
        workbench = next((row for row in rows if row["name"] == "workbench_api"), None)
        if any(row["classification"] == "timeout" for row in rows if row["plane"] == "api"):
            return "timeout"
        if frontend_started:
            frontend_passed = any(row["classification"] == "passed" for row in rows if row["plane"] == "frontend")
            frontend_failed = any(row["classification"] == "failed" for row in rows if row["plane"] == "frontend")
            if not frontend_passed and frontend_failed:
                return "failed"
        if workbench and workbench["classification"] == "surface_absent":
            return "partial"
        if frontend_started and not any(
            row["classification"] == "passed" for row in rows if row["plane"] == "frontend"
        ):
            return "partial"
        return "passed"
    if any(row["classification"] == "timeout" for row in rows):
        return "timeout"
    if any(row["classification"] == "blocked" for row in rows):
        return "blocked"
    if backend_started:
        return "failed"
    return "unavailable"


ProcessFactory = Callable[[str, list[str], int], ManagedProcess]


def default_factory(name: str, argv: list[str], log_cap: int) -> ManagedProcess:
    return ManagedProcess(name=name, argv=argv, log_cap_bytes=log_cap)


def run_rehearsal(
    config: StackConfig,
    *,
    environ: Mapping[str, str] | None = None,
    process_factory: ProcessFactory | None = None,
    backend_argv_override: list[str] | None = None,
    frontend_argv_override: list[str] | None = None,
) -> dict[str, Any]:
    factory = process_factory or default_factory
    env = fixture_environ(environ)
    config_errors = validate_stack_config(config)
    checks = (
        preflight(config)
        if not config_errors
        else {
            "configuration_valid": False,
            "configuration_errors": config_errors,
            "occupied_ports": {"api": False, "frontend": False},
        }
    )
    planned = {
        "backend": backend_argv_override or backend_argv(config),
        "frontend": frontend_argv_override or frontend_argv(config),
    }
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "mode": "fixture_only" if config.fixture_only else "unspecified",
        "dry_run": config.dry_run,
        "read_only": True,
        "mutated": False,
        "network_calls": False,
        # network_calls remains the external-network contract; only loopback HTTP is permitted.
        "external_network_calls": False,
        "network_scope": "loopback_only",
        "loopback_http_checks": False,
        "live_providers": False,
        "ports": {
            "api": {"host": config.api_host, "port": config.api_port},
            "frontend": {"host": config.frontend_host, "port": config.frontend_port},
        },
        "routes": {
            "api": [path for _, path in API_SURFACES],
            "frontend": [path for _, path in FRONTEND_SURFACES],
        },
        "planned_argv": planned,
        "preflight": checks,
        "classification": classify("not_run"),
        "surfaces": [],
        "cleanup": {},
        "logs": {},
        "cursor_browser": {
            "workbench": f"http://{config.frontend_host}:{config.frontend_port}/operator/services",
            "cockpit": f"http://{config.frontend_host}:{config.frontend_port}/operator/first-phase",
            "operator_events": f"http://{config.frontend_host}:{config.frontend_port}/operator/events",
            "note": "Do not duplicate Cursor UI tests; open these routes after --hold.",
        },
    }

    if config_errors:
        report["classification"] = classify("blocked")
        report["reason"] = "invalid_stack_config:" + ",".join(config_errors)
        return report

    occupied_reasons: list[str] = []
    if checks["occupied_ports"]["api"] is True and config.start_backend:
        occupied_reasons.append(f"api_port_occupied:{config.api_host}:{config.api_port}")
    if checks["occupied_ports"]["frontend"] is True and config.start_frontend:
        occupied_reasons.append(f"frontend_port_occupied:{config.frontend_host}:{config.frontend_port}")
    if occupied_reasons:
        report["classification"] = classify("blocked")
        report["reason"] = ",".join(occupied_reasons)
        return report

    if config.dry_run:
        report["classification"] = classify("not_run")
        report["reason"] = "dry_run_commands_documented_not_started"
        return report

    if not checks["python"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "python_missing"
        return report
    if config.start_backend and not checks["backend_api_module"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "backend_api_module_missing"
        return report
    if config.start_backend and not checks["uvicorn_importable"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "uvicorn_not_importable"
        return report

    if config.start_frontend and not checks["frontend_package_json"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "frontend_package_json_missing"
        return report
    if config.start_frontend and not checks["node"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "node_missing"
        report["surfaces"] = smoke_surfaces(config, backend_up=False, frontend_up=False)
        return report
    if config.start_frontend and not checks["npm"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "npm_missing"
        report["surfaces"] = smoke_surfaces(config, backend_up=False, frontend_up=False)
        return report

    managed: list[ManagedProcess] = []
    backend_up = False
    frontend_up = False
    startup_error: str | None = None
    try:
        if config.start_backend:
            backend = factory("backend", planned["backend"], config.log_cap_bytes)
            backend.start(cwd=config.repo, env=env)
            managed.append(backend)
            if wait_port(config.api_host, config.api_port, config.startup_timeout_s):
                ready_ok, ready_err = wait_health_ready(
                    config.api_host,
                    config.api_port,
                    "/health",
                    timeout_s=min(config.startup_timeout_s, 10.0),
                    request_timeout_s=config.request_timeout_s,
                    check_process=backend.poll,
                )
                if ready_ok:
                    backend_up = True
                else:
                    code = backend.poll()
                    startup_error = (
                        f"backend_exited:{code}"
                        if code is not None
                        else ("backend_startup_timeout" if ready_err == "readiness_timeout" else f"backend_readiness_failed:{ready_err}")
                    )
            else:
                code = backend.poll()
                startup_error = "backend_startup_timeout" if code is None else f"backend_exited:{code}"

        if config.start_frontend and startup_error is None:
            frontend = factory("frontend", planned["frontend"], config.log_cap_bytes)
            frontend.start(cwd=config.repo, env=env)
            managed.append(frontend)
            if wait_port(config.frontend_host, config.frontend_port, config.startup_timeout_s):
                frontend_up = True
            else:
                code = frontend.poll()
                startup_error = "frontend_startup_timeout" if code is None else f"frontend_exited:{code}"

        report["surfaces"] = smoke_surfaces(config, backend_up=backend_up, frontend_up=frontend_up)
        report["loopback_http_checks"] = backend_up or frontend_up
        if startup_error == "backend_startup_timeout" or startup_error == "frontend_startup_timeout":
            report["classification"] = classify("timeout")
            report["reason"] = startup_error
        elif startup_error:
            report["classification"] = classify("failed")
            report["reason"] = startup_error
        else:
            report["classification"] = classify(
                _overall(report["surfaces"], backend_started=backend_up, frontend_started=frontend_up)
            )
        if config.hold_s > 0 and report["classification"] in {"passed", "partial"}:
            deadline = time.monotonic() + config.hold_s
            while time.monotonic() < deadline:
                for item in managed:
                    code = item.poll()
                    if code is not None:
                        report["classification"] = classify("failed")
                        report["reason"] = f"{item.name}_exited_during_hold:{code}"
                        break
                if report["classification"] == "failed":
                    break
                time.sleep(min(0.2, max(0.02, deadline - time.monotonic())))
    except LocalOperatorStackError as exc:
        report["classification"] = classify("unavailable")
        report["reason"] = str(exc)
        if not report["surfaces"]:
            report["surfaces"] = smoke_surfaces(config, backend_up=False, frontend_up=False)
    finally:
        cleanup: dict[str, str] = {}
        logs: dict[str, str] = {}
        for item in managed:
            cleanup[item.name] = item.terminate()
            logs[item.name] = "" if cleanup[item.name] == "cleanup_failed" else item.drain_log()
        report["cleanup"] = cleanup
        report["logs"] = logs

        port_cleanup: dict[str, bool] = {}
        if config.start_backend:
            port_cleanup["api_port_free"] = wait_port_free(config.api_host, config.api_port, 2.0)
        if config.start_frontend:
            port_cleanup["frontend_port_free"] = wait_port_free(config.frontend_host, config.frontend_port, 2.0)
        report["port_cleanup"] = port_cleanup

        if any(status == "cleanup_failed" for status in cleanup.values()):
            report["classification"] = classify("failed")
            report["reason"] = "process_cleanup_failed"
        elif any(not free for free in port_cleanup.values()):
            report["classification"] = classify("failed")
            report["reason"] = "port_cleanup_failed"
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--api-host", default=DEFAULT_API_HOST)
    parser.add_argument("--api-port", type=int, default=DEFAULT_API_PORT)
    parser.add_argument("--frontend-host", default=DEFAULT_FRONTEND_HOST)
    parser.add_argument("--frontend-port", type=int, default=DEFAULT_FRONTEND_PORT)
    parser.add_argument("--startup-timeout", type=float, default=DEFAULT_STARTUP_TIMEOUT_S)
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT_S)
    parser.add_argument("--hold", type=float, default=0.0, help="seconds to keep processes after smoke")
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--frontend-only", action="store_true")
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument(
        "--execute",
        action="store_true",
        help="start fixture-only local services and perform loopback probes (opt-in)",
    )
    execution.add_argument(
        "--dry-run",
        action="store_true",
        help="plan only; this is also the default",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.backend_only and args.frontend_only:
        print(json.dumps({"error": "choose at most one of --backend-only / --frontend-only"}))
        return 2
    config = StackConfig(
        repo=args.repo.resolve(),
        api_host=args.api_host,
        api_port=args.api_port,
        frontend_host=args.frontend_host,
        frontend_port=args.frontend_port,
        startup_timeout_s=args.startup_timeout,
        request_timeout_s=args.request_timeout,
        hold_s=args.hold,
        start_backend=not args.frontend_only,
        start_frontend=not args.backend_only,
        dry_run=not args.execute,
    )
    report = run_rehearsal(config)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] in {"passed", "partial", "not_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
