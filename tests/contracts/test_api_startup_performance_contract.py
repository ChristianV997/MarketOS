"""Contract and regression tests for FastAPI startup and import boundaries.

Verifies that importing `backend.api` remains fast, does not eagerly load
the heavy numerical/causal execution loop into `sys.modules`, preserves all
registered routes, and provides a lazy backward-compatible accessor for `run_cycle`.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_backend_api_ast_has_no_top_level_loop_import():
    """Verify statically that backend/api.py has no top-level import of backend.execution.loop."""
    api_path = ROOT / "backend" / "api.py"
    source = api_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(api_path))

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "backend.execution.loop" not in alias.name, (
                    f"Found eager top-level import: import {alias.name} in backend/api.py"
                )
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert "backend.execution.loop" not in module_name, (
                f"Found eager top-level import: from {module_name} in backend/api.py"
            )


def test_isolated_api_import_defers_execution_loop_and_serves_health():
    """Verify in an isolated subprocess that importing backend.api does not load loop,

    preserves the /health endpoint, and lazily resolves run_cycle via __getattr__.
    """
    python_exe = sys.executable
    runner_script = """
import sys
import time

t0 = time.perf_counter()
import backend.api as api
t1 = time.perf_counter()

loop_loaded_eagerly = "backend.execution.loop" in sys.modules

from fastapi.testclient import TestClient
client = TestClient(api.app)
resp = client.get("/health")
t2 = time.perf_counter()

has_run_cycle_before = "backend.execution.loop" in sys.modules
run_cycle_callable = callable(getattr(api, "run_cycle", None))
loop_loaded_after_access = "backend.execution.loop" in sys.modules

all_paths = set()
for r in api.app.routes:
    if hasattr(r, "path"):
        all_paths.add(r.path)
    if hasattr(r, "original_router"):
        for inner in r.original_router.routes:
            if hasattr(inner, "path"):
                all_paths.add(inner.path)

output = {
    "import_duration_s": t1 - t0,
    "total_health_setup_s": t2 - t0,
    "loop_loaded_eagerly": loop_loaded_eagerly,
    "health_status": resp.status_code,
    "health_json": resp.json(),
    "has_health_route": "/health" in all_paths,
    "has_metrics_route": "/metrics/prometheus" in all_paths,
    "route_count": len(all_paths),
    "run_cycle_callable": run_cycle_callable,
    "loop_loaded_after_access": loop_loaded_after_access,
}

import json
print("__BENCHMARK_OUTPUT__:" + json.dumps(output))
"""
    proc = subprocess.Popen(
        [python_exe, "-c", runner_script],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail("API startup and health check timed out after 60 seconds (startup bottleneck detected)")

    assert proc.returncode == 0, f"Subprocess failed with code {proc.returncode}:\n{stderr}\n{stdout}"

    marker = "__BENCHMARK_OUTPUT__:"
    assert marker in stdout, f"Marker missing from output:\n{stdout}\n{stderr}"
    data_str = stdout.split(marker, 1)[1].strip().split("\n")[0]
    data = json.loads(data_str)

    # 1. Execution loop must not be loaded during module import
    assert data["loop_loaded_eagerly"] is False, (
        "backend.execution.loop was loaded eagerly during import backend.api!"
    )

    # 2. Health endpoint works and responds 200 {"ok": True, ...}
    assert data["health_status"] == 200
    assert data["health_json"].get("ok") is True
    assert data["has_health_route"] is True
    assert data["has_metrics_route"] is True
    assert data["route_count"] >= 50

    # 3. run_cycle remains accessible and callable via module attribute access
    assert data["run_cycle_callable"] is True
    assert data["loop_loaded_after_access"] is True


_ASGI_RUNNER = r"""
import asyncio, json, sys
from unittest import mock
import backend.api as api

def call(method, path):
    sent = []
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": [(b"host", b"t"), (b"content-length", b"0")], "client": ("127.0.0.1", 1), "server": ("t", 80)}
    asyncio.run(api.app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")

LOOP = "backend.execution.loop"
out = {"loaded_at_import": LOOP in sys.modules}
out["health"] = call("GET", "/health")
out["loaded_after_health"] = LOOP in sys.modules
out["risk_status"] = call("GET", "/risk/status")
out["loaded_after_risk_status"] = LOOP in sys.modules
out["agents"] = call("GET", "/agents")
out["loaded_after_agents"] = LOOP in sys.modules
import backend.execution.loop as loop
with mock.patch.object(loop, "run_cycle", side_effect=lambda state: state) as patched:
    out["cycle"] = call("POST", "/cycle")
    out["cycle_used_patched_loop"] = patched.called
with mock.patch.object(loop, "run_cycle", side_effect=RuntimeError("offline-failure")):
    try:
        call("POST", "/cycle")
        out["cycle_error"] = "swallowed"
    except RuntimeError:
        out["cycle_error"] = "propagated"
print("__ASGI__:" + json.dumps(out))
"""


def _run_asgi_scenario() -> dict:
    proc = subprocess.run(
        [sys.executable, "-B", "-c", _ASGI_RUNNER],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(proc.stdout.split("__ASGI__:", 1)[1].splitlines()[0])


def test_lazy_route_imports_load_on_first_use_and_routes_still_answer():
    """Offline, no HTTP client: /health and /risk/status leave the loop unloaded; /agents and /cycle load it.

    The routes keep answering 200, and a failing cycle still propagates to the caller as before.
    """
    data = _run_asgi_scenario()
    assert data["loaded_at_import"] is False
    assert data["health"] == 200 and data["loaded_after_health"] is False
    assert data["risk_status"] == 200 and data["loaded_after_risk_status"] is False
    assert data["agents"] == 200 and data["loaded_after_agents"] is True
    assert data["cycle"] == 200 and data["cycle_used_patched_loop"] is True
    assert data["cycle_error"] == "propagated"


def test_route_modules_have_no_top_level_loop_import():
    for relative in ("api/routes/cycle_control.py", "api/routes/agents_risk.py"):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"), filename=relative)
        for node in tree.body:
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any("backend.execution.loop" in name for name in names), f"eager loop import in {relative}"
