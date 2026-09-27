"""backend.deployment.diagnostics -- Actionable failure diagnostics for MarketOS deployment and local development.

Covers 11 failure conditions:
1. missing Python module
2. missing Node dependency
3. missing optional provider
4. missing Docker
5. unavailable Ollama
6. zero-step CI
7. missing runner
8. malformed report
9. failed healthcheck
10. port collision
11. invalid environment contract
"""
from __future__ import annotations

import importlib
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class DiagnosticResult:
    code: str
    category: str
    status: str  # "ok", "detected", "unavailable", "warning"
    message: str
    remediation: str
    failure_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "status": self.status,
            "message": self.message,
            "remediation": self.remediation,
            "failure_details": dict(self.failure_details),
        }


def diagnose_missing_python_module(module_name: str) -> DiagnosticResult:
    """Diagnose whether a required Python module is missing."""
    try:
        importlib.import_module(module_name)
        return DiagnosticResult(
            code="missing_python_module",
            category="runtime_dependency",
            status="ok",
            message=f"Python module '{module_name}' is installed and importable.",
            remediation="No action required.",
            failure_details={"module": module_name, "found": True},
        )
    except Exception as exc:
        return DiagnosticResult(
            code="missing_python_module",
            category="runtime_dependency",
            status="detected",
            message=f"Required Python module '{module_name}' is missing or failed to import ({type(exc).__name__}: {exc}).",
            remediation=f"Run `pip install -r requirements.txt` in the active virtual environment or install '{module_name}'.",
            failure_details={"module": module_name, "error": str(exc), "error_type": type(exc).__name__},
        )


def diagnose_missing_node_dependency(frontend_dir: Path | None = None) -> DiagnosticResult:
    """Diagnose missing frontend/node_modules dependencies."""
    base = frontend_dir or (ROOT / "frontend")
    node_modules = base / "node_modules"
    pkg_json = base / "package.json"

    if not pkg_json.exists():
        return DiagnosticResult(
            code="missing_node_dependency",
            category="frontend_dependency",
            status="unavailable",
            message="frontend/package.json not found in this checkout.",
            remediation="Ensure frontend source files are present.",
            failure_details={"path": str(base), "has_package_json": False},
        )

    if not node_modules.is_dir():
        return DiagnosticResult(
            code="missing_node_dependency",
            category="frontend_dependency",
            status="detected",
            message="frontend/node_modules directory is absent.",
            remediation="Run `cd frontend && npm ci --ignore-scripts --no-audit --no-fund` in an isolated worktree.",
            failure_details={"node_modules_present": False, "path": str(node_modules)},
        )

    return DiagnosticResult(
        code="missing_node_dependency",
        category="frontend_dependency",
        status="ok",
        message="frontend/node_modules is present.",
        remediation="No action required.",
        failure_details={"node_modules_present": True},
    )


def diagnose_missing_optional_provider(
    provider_name: str,
    environ: Mapping[str, str] | None = None,
) -> DiagnosticResult:
    """Diagnose missing credentials or configuration for optional providers."""
    env = os.environ if environ is None else environ
    provider_key_map = {
        "apify": ("APIFY_API_TOKEN",),
        "dataforseo": ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"),
        "serpapi": ("SERPAPI_API_KEY",),
        "shopify": ("SHOPIFY_ACCESS_TOKEN",),
        "cj": ("CJ_API_KEY", "CJ_EMAIL"),
        "stripe": ("STRIPE_SECRET_KEY",),
    }
    keys = provider_key_map.get(provider_name.lower(), (f"{provider_name.upper()}_API_KEY",))
    missing = [k for k in keys if not env.get(k)]

    if missing:
        return DiagnosticResult(
            code="missing_optional_provider",
            category="provider_credentials",
            status="detected",
            message=f"Optional provider '{provider_name}' lacks credentials ({', '.join(missing)}).",
            remediation=f"MarketOS defaults to offline deterministic fixtures. Live provider activation requires an evidence-backed Approval Ledger policy; do not commit secrets to .env or git.",
            failure_details={"provider": provider_name, "missing_keys": missing, "offline_fallback_ready": True},
        )

    return DiagnosticResult(
        code="missing_optional_provider",
        category="provider_credentials",
        status="ok",
        message=f"Optional provider '{provider_name}' configuration is present in environment.",
        remediation="Verify Approval Ledger gate before executing live calls.",
        failure_details={"provider": provider_name, "configured": True},
    )


def diagnose_missing_docker() -> DiagnosticResult:
    """Diagnose whether Docker CLI is available."""
    docker_path = shutil.which("docker")
    if not docker_path:
        return DiagnosticResult(
            code="missing_docker",
            category="container_runtime",
            status="detected",
            message="Docker CLI executable is not found in PATH.",
            remediation="Docker is optional for local development. MarketOS local dry-run is fully supported directly via Python (`uvicorn backend.api:app`). Install Docker Desktop or Docker engine if container rehearsal is required.",
            failure_details={"in_path": False},
        )

    return DiagnosticResult(
        code="missing_docker",
        category="container_runtime",
        status="ok",
        message=f"Docker CLI found at '{docker_path}'.",
        remediation="No action required.",
        failure_details={"in_path": True, "executable": docker_path},
    )


def diagnose_unavailable_ollama(host: str = "127.0.0.1", port: int = 11434) -> DiagnosticResult:
    """Diagnose whether Ollama local inference service is reachable."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        result = sock.connect_ex((host, port))
        is_reachable = result == 0
    except OSError:
        is_reachable = False
    finally:
        sock.close()

    if not is_reachable:
        return DiagnosticResult(
            code="unavailable_ollama",
            category="local_inference",
            status="detected",
            message=f"Ollama inference daemon is not reachable on {host}:{port}.",
            remediation="MarketOS falls back to deterministic offline mock inference. Start Ollama (`ollama serve`) if local LLM inference is explicitly desired.",
            failure_details={"host": host, "port": port, "reachable": False},
        )

    return DiagnosticResult(
        code="unavailable_ollama",
        category="local_inference",
        status="ok",
        message=f"Ollama inference service is reachable on {host}:{port}.",
        remediation="No action required.",
        failure_details={"host": host, "port": port, "reachable": True},
    )


def diagnose_zero_step_ci(
    ci_status: str = "ci_unavailable",
    steps_executed: int = 0,
    runner_id: int | None = None,
    annotations: list[str] | None = None,
) -> DiagnosticResult:
    """Diagnose zero-step or unavailable CI pipeline."""
    zero_runner = runner_id is not None and runner_id == 0
    if ci_status in {"ci_unavailable", "unavailable"} or steps_executed == 0 or zero_runner:
        msg = f"Continuous Integration reported '{ci_status}' with {steps_executed} steps executed."
        msg += " Runner allocation or workflow startup is unavailable; cause is unverified."
        return DiagnosticResult(
            code="zero_step_ci",
            category="continuous_integration",
            status="detected",
            message=msg,
            remediation="Remote CI cannot validate PRs in zero-step mode. Run `python scripts/ai/run_local_quality_gate.py --from-git` and `python scripts/ai/session_finish.py --dry-run` locally before submitting.",
            failure_details={
                "ci_status": ci_status,
                "steps_executed": steps_executed,
                "runner_id": runner_id,
                "runner_assigned": runner_id is not None and runner_id > 0,
                "cause_verified": False,
            },
        )

    return DiagnosticResult(
        code="zero_step_ci",
        category="continuous_integration",
        status="ok",
        message=f"CI is active ({ci_status}, {steps_executed} steps).",
        remediation="No action required.",
        failure_details={"ci_status": ci_status, "steps_executed": steps_executed, "runner_id": runner_id},
    )


def diagnose_missing_runner() -> DiagnosticResult:
    """Diagnose availability of platform execution runner."""
    is_windows = sys.platform == "win32"
    shell_available = bool(shutil.which("powershell.exe") if is_windows else shutil.which("bash"))
    python_available = bool(sys.executable)

    if not python_available or not shell_available:
        return DiagnosticResult(
            code="missing_runner",
            category="execution_environment",
            status="detected",
            message="Host execution runner (Python or native shell) is degraded.",
            remediation="Ensure Python 3.12+ and PowerShell/Bash are accessible in system PATH.",
            failure_details={"is_windows": is_windows, "python": python_available, "shell": shell_available},
        )

    return DiagnosticResult(
        code="missing_runner",
        category="execution_environment",
        status="ok",
        message="Host execution runner is available.",
        remediation="No action required.",
        failure_details={"is_windows": is_windows, "python": sys.executable},
    )


def diagnose_malformed_report(report_data: Any, required_fields: tuple[str, ...]) -> DiagnosticResult:
    """Diagnose malformed JSON reports or schema violations."""
    if not isinstance(report_data, dict):
        return DiagnosticResult(
            code="malformed_report",
            category="report_integrity",
            status="detected",
            message="Report data root is not a dictionary.",
            remediation="Ensure report generation logic emits valid JSON objects matching the schema specification.",
            failure_details={"root_type": type(report_data).__name__},
        )

    missing = [k for k in required_fields if k not in report_data]
    if missing:
        return DiagnosticResult(
            code="malformed_report",
            category="report_integrity",
            status="detected",
            message=f"Report is missing required schema fields: {', '.join(missing)}.",
            remediation="Update generator serializer to populate all mandatory contract fields.",
            failure_details={"missing_fields": missing},
        )

    return DiagnosticResult(
        code="malformed_report",
        category="report_integrity",
        status="ok",
        message="Report conforms to required schema fields.",
        remediation="No action required.",
        failure_details={"checked_fields": list(required_fields)},
    )


def diagnose_failed_healthcheck(host: str = "127.0.0.1", port: int = 3000) -> DiagnosticResult:
    """Diagnose API healthcheck reachability."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        conn = sock.connect_ex((host, port))
        reachable = conn == 0
    except OSError:
        reachable = False
    finally:
        sock.close()

    if not reachable:
        return DiagnosticResult(
            code="failed_healthcheck",
            category="api_liveness",
            status="detected",
            message=f"API server is not responding on {host}:{port}/health.",
            remediation=f"Start the FastAPI server via `uvicorn backend.api:app --host {host} --port {port}` or verify container logs.",
            failure_details={"host": host, "port": port, "reachable": False},
        )

    return DiagnosticResult(
        code="failed_healthcheck",
        category="api_liveness",
        status="ok",
        message=f"API server is responding on {host}:{port}.",
        remediation="No action required.",
        failure_details={"host": host, "port": port, "reachable": True},
    )


def diagnose_port_collision(port: int = 3000, host: str = "127.0.0.1") -> DiagnosticResult:
    """Diagnose whether a required port is already bound by another process."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        collision = False
    except OSError:
        collision = True
    finally:
        sock.close()

    if collision:
        return DiagnosticResult(
            code="port_collision",
            category="networking",
            status="detected",
            message=f"Port {port} on {host} is already in use by another process.",
            remediation=f"Stop the conflicting process on port {port} or configure an alternate PORT environment variable.",
            failure_details={"host": host, "port": port, "collision": True},
        )

    return DiagnosticResult(
        code="port_collision",
        category="networking",
        status="ok",
        message=f"Port {port} on {host} is available for binding.",
        remediation="No action required.",
        failure_details={"host": host, "port": port, "collision": False},
    )


def diagnose_invalid_environment_contract(
    environ: Mapping[str, str] | None = None,
    mode: str = "local_dry_run",
) -> DiagnosticResult:
    """Diagnose contract violations in the execution environment."""
    from backend.deployment.environment_contract import validate_environment

    report = validate_environment(environ=environ, mode=mode)
    if not report.ready:
        return DiagnosticResult(
            code="invalid_environment_contract",
            category="environment_governance",
            status="detected",
            message=f"Environment contract validation failed for mode '{mode}' with {len(report.blockers)} blocker(s).",
            remediation=f"Resolve blockers before starting: {'; '.join(report.blockers)}.",
            failure_details={"mode": mode, "blockers": report.blockers, "warnings": report.warnings},
        )

    return DiagnosticResult(
        code="invalid_environment_contract",
        category="environment_governance",
        status="ok",
        message=f"Environment conforms to '{mode}' contract requirements.",
        remediation="No action required.",
        failure_details={"mode": mode, "ready": True},
    )


def diagnose_service_delivery_readiness(
    environ: Mapping[str, str] | None = None,
    base_url: str | None = None,
) -> DiagnosticResult:
    """Diagnose readiness of service delivery workbench projection and router."""
    env = os.environ if environ is None else environ
    proj_val = env.get("MARKETOS_SERVICE_DELIVERY_PROJECTION", "")

    # Check route availability
    route_installed = False
    try:
        import importlib
        importlib.import_module("api.routes.service_delivery_workbench")
        route_installed = True
    except ModuleNotFoundError:
        route_installed = False

    if not proj_val and not route_installed:
        return DiagnosticResult(
            code="service_delivery_readiness",
            category="service_delivery",
            status="detected",
            message="Service delivery workbench route is unmerged (PR #271) and projection is unconfigured.",
            remediation="Merge PR #271 and configure MARKETOS_SERVICE_DELIVERY_PROJECTION pointing to an artifact under artifacts/.",
            failure_details={"route_installed": False, "projection_configured": False},
        )

    if not proj_val:
        return DiagnosticResult(
            code="service_delivery_readiness",
            category="service_delivery",
            status="detected",
            message="Service delivery projection is not configured (MARKETOS_SERVICE_DELIVERY_PROJECTION is unset).",
            remediation="Run `python scripts/generate_service_delivery_projection.py` and set MARKETOS_SERVICE_DELIVERY_PROJECTION.",
            failure_details={"route_installed": route_installed, "projection_configured": False},
        )

    from backend.deployment.service_delivery_smoke import validate_service_delivery_projection
    proj_report = validate_service_delivery_projection(path=proj_val, environ=env)
    if proj_report["status"] != "passed":
        return DiagnosticResult(
            code="service_delivery_readiness",
            category="service_delivery",
            status="detected",
            message=f"Service delivery projection validation returned '{proj_report['status']}': {proj_report.get('reason')}",
            remediation=f"Resolve projection issue: {proj_report.get('message')}",
            failure_details=proj_report,
        )

    return DiagnosticResult(
        code="service_delivery_readiness",
        category="service_delivery",
        status="ok",
        message="Service delivery projection and contract are valid.",
        remediation="No action required.",
        failure_details={"route_installed": route_installed, "projection_status": "passed"},
    )


def _zero_step_ci_diagnosis(ci_evidence: Any) -> DiagnosticResult:
    """Resolve the diagnose_zero_step_ci() call from optional caller-supplied
    CI evidence, failing closed rather than silently ignoring a malformed
    value.

    Before this existed, run_all_diagnostics() always called
    diagnose_zero_step_ci() with no arguments -- so a caller's actual,
    observed CI evidence (e.g. from a real GitHub Actions job with
    runner_id=0 or an empty steps list) never reached this diagnostic's
    administrator-facing message at all, no matter what was really
    observed. diagnose_zero_step_ci() itself is unchanged and still the
    single authority for this classification; this only decides what
    gets passed into it.
    """
    if ci_evidence is None:
        return diagnose_zero_step_ci()
    if not isinstance(ci_evidence, Mapping):
        return DiagnosticResult(
            code="zero_step_ci",
            category="continuous_integration",
            status="detected",
            message="CI evidence supplied to diagnostics was not a mapping and could not be classified.",
            remediation="Pass a {ci_status, steps_executed, runner_id} mapping, or omit ci_evidence entirely.",
            failure_details={"ci_status": "malformed", "steps_executed": 0, "runner_id": None},
        )
    try:
        steps_executed = int(ci_evidence.get("steps_executed", 0) or 0)
    except (TypeError, ValueError):
        steps_executed = 0
    runner_id_raw = ci_evidence.get("runner_id")
    runner_id = int(runner_id_raw) if isinstance(runner_id_raw, (int, float)) and not isinstance(runner_id_raw, bool) else None
    ci_status = str(ci_evidence.get("ci_status", "ci_unavailable") or "ci_unavailable")
    return diagnose_zero_step_ci(ci_status=ci_status, steps_executed=steps_executed, runner_id=runner_id)


def run_all_diagnostics(
    environ: Mapping[str, str] | None = None,
    mode: str = "local_dry_run",
    include_service_delivery: bool = False,
    ci_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute all diagnostic checks and aggregate results.

    ``ci_evidence``, when supplied, threads a caller's actual observed CI
    state ({ci_status, steps_executed, runner_id}) into the zero-step-CI
    diagnostic instead of that check always running with no evidence at
    all. Omitting it (the default) reproduces the prior behavior exactly.
    """
    results = [
        diagnose_missing_python_module("fastapi"),
        diagnose_missing_node_dependency(),
        diagnose_missing_optional_provider("apify", environ=environ),
        diagnose_missing_optional_provider("dataforseo", environ=environ),
        diagnose_missing_docker(),
        diagnose_unavailable_ollama(),
        _zero_step_ci_diagnosis(ci_evidence),
        diagnose_missing_runner(),
        diagnose_port_collision(3000),
        diagnose_invalid_environment_contract(environ=environ, mode=mode),
    ]
    if include_service_delivery:
        results.append(diagnose_service_delivery_readiness(environ=environ))

    detected = [r for r in results if r.status == "detected"]
    ok = [r for r in results if r.status == "ok"]

    return {
        "schema": "MarketOS.DeploymentDiagnostics.v1",
        "mode": mode,
        "summary": {
            "total_checks": len(results),
            "detected_issues": len(detected),
            "healthy_checks": len(ok),
            "status": "issues_detected" if detected else "all_checks_healthy",
        },
        "diagnostics": [r.to_dict() for r in results],
    }


__all__ = [
    "DiagnosticResult",
    "diagnose_missing_python_module",
    "diagnose_missing_node_dependency",
    "diagnose_missing_optional_provider",
    "diagnose_missing_docker",
    "diagnose_unavailable_ollama",
    "diagnose_zero_step_ci",
    "diagnose_missing_runner",
    "diagnose_malformed_report",
    "diagnose_failed_healthcheck",
    "diagnose_port_collision",
    "diagnose_invalid_environment_contract",
    "diagnose_service_delivery_readiness",
    "run_all_diagnostics",
]
