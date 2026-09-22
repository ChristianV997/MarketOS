"""Loopback lifecycle for the operator browser acceptance harness.

This module does not start providers, spend, or publish. It probes ports,
classifies evidence, redacts local reports, and stops only processes it spawned.

Evidence classes:
  - fixture_browser_tested: Chrome/Orca against the fixture harness
  - local_ui_tested: loopback Vite/API that an operator already started
  - live_validated: never emitted by this module
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
EVIDENCE_FIXTURE = "fixture_browser_tested"
EVIDENCE_LOCAL_UI = "local_ui_tested"
EVIDENCE_LIVE = "live_validated"
ALLOWED_EVIDENCE = frozenset({EVIDENCE_FIXTURE, EVIDENCE_LOCAL_UI})

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|password|secret)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bsk_live_[A-Za-z0-9]+\b"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+"),
    re.compile(r"/home/[^/\s]+"),
    re.compile(r"/Users/[^/\s]+"),
)


@dataclass
class StackProbe:
    api_base: str
    ui_base: str
    api_ready: bool
    ui_ready: bool
    api_status: int
    ui_status: int
    evidence_class: str
    note: str


@dataclass
class ManagedProcess:
    name: str
    popen: subprocess.Popen[str]
    pid: int


@dataclass
class StackSession:
    processes: list[ManagedProcess] = field(default_factory=list)
    stopped: bool = False

    def track(self, name: str, proc: subprocess.Popen[str]) -> None:
        self.processes.append(ManagedProcess(name=name, popen=proc, pid=int(proc.pid)))

    def stop(self, timeout_s: float = 5.0) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for item in self.processes:
            code = _terminate(item.popen, timeout_s=timeout_s)
            results.append({"name": item.name, "pid": item.pid, "returncode": code})
        self.stopped = True
        return results


def is_loopback(host: str) -> bool:
    return host.strip().lower() in LOOPBACK_HOSTS


def port_open(host: str, port: int, timeout_s: float = 0.3) -> bool:
    if not is_loopback(host):
        return False
    if type(port) is not int or not 1 <= port <= 65535:
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def wait_until_ready(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        if port_open(host, port):
            return True
        time.sleep(0.1)
    return port_open(host, port)


def http_status(url: str, timeout_s: float = 2.0) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except Exception:
        return 0


def classify_evidence(*, browser_executed: bool, live_ui: bool) -> str:
    """Local and fixture runs never become live_validated."""
    if live_ui:
        return EVIDENCE_LOCAL_UI
    if browser_executed:
        return EVIDENCE_FIXTURE
    return EVIDENCE_FIXTURE


def assert_not_live(label: str) -> None:
    if label == EVIDENCE_LIVE or label not in ALLOWED_EVIDENCE:
        raise ValueError(f"evidence_class_rejected:{label}")


def redact_text(text: str) -> str:
    cleaned = text
    for pattern in SECRET_PATTERNS:
        cleaned = pattern.sub("[redacted]", cleaned)
    return cleaned


def redact_report(payload: Mapping[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(payload, default=str)
    return json.loads(redact_text(encoded))


def probe_stack(api_base: str, ui_base: str) -> StackProbe:
    api = _parse(api_base)
    ui = _parse(ui_base)
    if api.hostname not in LOOPBACK_HOSTS or ui.hostname not in LOOPBACK_HOSTS:
        return StackProbe(api_base, ui_base, False, False, 0, 0, EVIDENCE_LOCAL_UI, "rejected_non_loopback")
    api_status = http_status(f"{api_base.rstrip('/')}/ready")
    ui_status = http_status(ui_base)
    api_ready = 200 <= api_status < 500
    ui_ready = 200 <= ui_status < 400
    if api_ready and ui_ready:
        note = "local_stack_reachable"
    elif ui_ready:
        note = "ui_only"
    elif api_ready:
        note = "api_only"
    else:
        note = "stack_unavailable"
    return StackProbe(
        api_base=api_base,
        ui_base=ui_base,
        api_ready=api_ready,
        ui_ready=ui_ready,
        api_status=api_status,
        ui_status=ui_status,
        evidence_class=EVIDENCE_LOCAL_UI,
        note=note,
    )


def _parse(url: str):
    from urllib.parse import urlparse

    return urlparse(url)


def powershell_command(repo: Path, extra: list[str] | None = None) -> list[str]:
    """Arguments a Windows operator can pass to python. No shell=True."""
    script = repo / "scripts" / "ai" / "run_operator_browser_acceptance.py"
    return [sys.executable, str(script), "--browser", "chrome", "--json", *(extra or [])]


def spawn_tracked(session: StackSession, name: str, argv: list[str], *, cwd: Path) -> int:
    proc = subprocess.Popen(
        argv,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    session.track(name, proc)
    return int(proc.pid)


def _terminate(proc: subprocess.Popen[str], timeout_s: float) -> int | None:
    if proc.poll() is not None:
        return proc.returncode
    proc.terminate()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=timeout_s)
    return proc.returncode


def artifact_dir_is_safe(path: Path) -> bool:
    resolved = path.resolve()
    parts = {part.lower() for part in resolved.parts}
    if ".git" in parts:
        return False
    text = str(resolved)
    if "node_modules" in text or "frontend" + os.sep + "src" in text:
        return False
    return True


def scenario_matrix() -> list[dict[str, Any]]:
    routes = ("/operator/services", "/operator/first-phase", "/operator/events")
    modes = {
        "ok-fixture": "blocked_or_partial",
        "down": "unavailable",
        "429": "unavailable",
        "500": "unavailable",
        "malformed": "unavailable",
        "empty": "empty",
        "stale": "stale",
        "loading": "loading",
    }
    viewports = ((375, 812), (390, 844), (768, 1024), (1440, 900))
    rows: list[dict[str, Any]] = []
    for route in routes:
        for mode, surface in modes.items():
            for width, height in viewports:
                rows.append(
                    {
                        "route": route,
                        "api_mode": mode,
                        "width": width,
                        "height": height,
                        "expected_surface": surface,
                        "allowed_methods": ["GET"],
                        "evidence_class": EVIDENCE_FIXTURE,
                        "live_validated": False,
                    }
                )
    return rows


def write_scenario_matrix(path: Path) -> int:
    rows = scenario_matrix()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "MarketOS.OperatorBrowserScenarioMatrix.v1", "rows": rows}, indent=2), encoding="utf-8")
    return len(rows)
