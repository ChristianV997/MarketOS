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
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
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
_SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|authorization|password|secret|bearer\s+\S+|sk-(?:live|proj)-[A-Za-z0-9]+|ghp_[A-Za-z0-9]+)"
)


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
    dry_run: bool = False
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


def redact(text: str) -> str:
    if not text:
        return ""
    return _SECRET_RE.sub("[redacted]", text)


def cap_log(text: str, cap_bytes: int) -> str:
    raw = (text or "").encode("utf-8", errors="replace")
    if len(raw) <= cap_bytes:
        return text or ""
    kept = raw[:cap_bytes].decode("utf-8", errors="replace")
    return kept + f"\n...[truncated {len(raw) - cap_bytes} bytes]"


def fixture_environ(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in SECRET_ENV_KEYS:
        env.pop(key, None)
    env["MARKETOS_MVP_MODE"] = "1"
    env["MARKETOS_PUBLIC_COMMERCE_RUNS"] = "0"
    env["ORCHESTRATOR_HANDLES_CYCLES"] = "true"
    env["ALLOWED_ORIGINS"] = env.get("ALLOWED_ORIGINS") or "http://127.0.0.1:5173"
    env["CYCLES_PER_MINUTE"] = env.get("CYCLES_PER_MINUTE") or "1"
    env["MARKETOS_ALLOW_LIVE"] = "0"
    env["MARKETOS_LIVE_PROVIDERS"] = "0"
    return env


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

    def start(self, *, cwd: Path, env: Mapping[str, str]) -> None:
        try:
            self.proc = subprocess.Popen(
                self.argv,
                cwd=str(cwd),
                env=dict(env),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
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
        if self.proc.poll() is not None:
            return "already_exited"
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                self.proc.terminate()
            except OSError:
                pass
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and self.proc.poll() is None:
            time.sleep(0.05)
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    self.proc.kill()
                except OSError:
                    pass
            try:
                self.proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
            return "killed"
        return "terminated"

    def drain_log(self) -> str:
        if self.proc is None or self.proc.stdout is None:
            return ""
        try:
            chunk = self.proc.stdout.read() or ""
        except OSError:
            chunk = ""
        return cap_log(redact(chunk), self.log_cap_bytes)


def http_get(url: str, timeout_s: float) -> dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read(2048)
            return {
                "url": url,
                "http_status": int(response.status),
                "classification": classify("passed" if 200 <= response.status < 400 else "failed"),
                "bytes": len(body),
            }
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        if status == 404:
            kind = "surface_absent"
        elif 400 <= status < 500:
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
    occupied = {
        "api": port_bind_conflict(config.api_host, config.api_port),
        "frontend": port_bind_conflict(config.frontend_host, config.frontend_port),
    }
    return {
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
        if workbench and workbench["classification"] == "surface_absent":
            return "partial"
        if any(row["classification"] == "timeout" for row in rows if row["plane"] == "api"):
            return "timeout"
        if frontend_started and any(
            row["classification"] == "passed" for row in rows if row["plane"] == "frontend"
        ):
            return "passed"
        if frontend_started:
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
    checks = preflight(config)
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

    if checks["occupied_ports"]["api"] and config.start_backend:
        report["classification"] = classify("blocked")
        report["reason"] = f"api_port_occupied:{config.api_host}:{config.api_port}"
        return report
    if checks["occupied_ports"]["frontend"] and config.start_frontend:
        report["classification"] = classify("blocked")
        report["reason"] = f"frontend_port_occupied:{config.frontend_host}:{config.frontend_port}"
        return report

    if config.dry_run:
        report["classification"] = classify("not_run")
        report["reason"] = "dry_run_commands_documented_not_started"
        return report

    if config.start_backend and not checks["backend_api_module"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "backend_api_module_missing"
        return report
    if config.start_frontend and not checks["frontend_package_json"]:
        report["classification"] = classify("unavailable")
        report["reason"] = "frontend_package_json_missing"
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
                backend_up = True
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
            time.sleep(config.hold_s)
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
            logs[item.name] = item.drain_log()
        report["cleanup"] = cleanup
        report["logs"] = logs
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
    parser.add_argument("--dry-run", action="store_true")
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
        dry_run=args.dry_run,
    )
    report = run_rehearsal(config)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] in {"passed", "partial", "not_run"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
