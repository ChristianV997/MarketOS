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
