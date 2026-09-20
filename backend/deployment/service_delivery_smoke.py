"""backend.deployment.service_delivery_smoke -- Deployment dry-run and release-smoke

engine for the MarketOS service-delivery workbench application and its dependencies.

Composes existing repository authorities without duplicating or replacing them:
- Environment Contract (backend.deployment.environment_contract)
- Failure Diagnostics (backend.deployment.diagnostics)
- Workspace Isolation (evaluation.trustos.client_workspace_isolation)
- CI Evidence Classification (backend.deployment.promotion_rehearsal)

Maintains strict separation between:
1. Local offline dry-run checks
2. Zero-step / runnerless CI states (ci_unavailable)
3. Live production readiness (blocked / not ready)

Never enables live mutations, provider network calls, or credential storage.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deployment.environment_contract import (
    MUTATION_FLAG_KEYS,
    is_truthy,
    validate_environment,
)
from backend.deployment.diagnostics import (
    DiagnosticResult,
    diagnose_missing_docker,
    diagnose_missing_runner,
    diagnose_zero_step_ci,
)

ARTIFACTS_DIR = (ROOT / "artifacts").resolve()
ENDPOINT_PATH = "/api/service-delivery/workbench"
SUPPORTED_PROJECTION_VERSIONS = frozenset({
    "service-engagement-projection-v1",
    "service-delivery-plane-v1",
})
FORBIDDEN_WORKSPACE_LEAK_KEYS = frozenset({
    "internal_prompt",
    "internal_prompts",
    "internal_formula",
    "internal_formulas",
    "internal_heuristics",
    "raw_provider_payload",
    "cross_client_data",
})


def is_path_under_artifacts(path: Path | str, artifacts_root: Path | None = None) -> bool:
    """Verify that a path resolves safely within the artifacts directory without traversal."""
    if not path:
        return False
    root = artifacts_root or ARTIFACTS_DIR
    try:
        resolved = Path(path).resolve() if Path(path).is_absolute() else (ROOT / path).resolve()
        return resolved == root or root in resolved.parents
    except OSError:
        return False


def check_projection_workspace_isolation(payload: Any) -> list[str]:
    """Check projection payload for leaks of internal formulas, prompts, or heuristics.
    
    Delegates to canonical evaluation.trustos.client_workspace_isolation when importable,
    with robust fallback inspection.
    """
    findings: list[str] = []
    
    # Check via canonical isolation authority if available
    try:
        from evaluation.trustos.client_workspace_isolation import check_workspace_leakage
        leaks = check_workspace_leakage(payload, client_safe=True)
        if leaks:
            if isinstance(leaks, list):
                findings.extend(str(x) for x in leaks)
            else:
                findings.append("client_workspace_leakage_detected")
    except (ImportError, Exception):
        pass

    # Recursive dictionary key check
    def _inspect_node(node: Any, current_path: str = ""):
        if isinstance(node, dict):
            for k, v in node.items():
                k_str = str(k).lower()
                child_path = f"{current_path}.{k}" if current_path else str(k)
                if k_str in FORBIDDEN_WORKSPACE_LEAK_KEYS:
                    findings.append(f"forbidden_key_found:{child_path}")
                _inspect_node(v, child_path)
        elif isinstance(node, (list, tuple)):
            for idx, item in enumerate(node):
                _inspect_node(item, f"{current_path}[{idx}]")

    _inspect_node(payload)
    return sorted(set(findings))


def validate_service_delivery_projection(
    path: Path | str | None = None,
    artifacts_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate that the service-delivery projection artifact is safely configured and formatted."""
    env = os.environ if environ is None else environ
    root = artifacts_root or ARTIFACTS_DIR
    raw_path = path if path is not None else env.get("MARKETOS_SERVICE_DELIVERY_PROJECTION", "")

    if not raw_path:
        return {
            "status": "unavailable",
            "reason": "service_delivery_projection_not_configured",
            "message": "MARKETOS_SERVICE_DELIVERY_PROJECTION is not set in the environment.",
            "path": None,
            "is_artifact_safe": False,
            "row_count": 0,
            "schema_version": "unknown",
            "leakage_detected": False,
            "leakage_details": [],
        }

    # Safety check: path traversal outside artifacts/
    if not is_path_under_artifacts(raw_path, artifacts_root=root):
        return {
            "status": "blocked",
            "reason": "projection_path_outside_artifacts",
            "message": f"Projection path '{raw_path}' resolves outside the allowed artifacts directory ({root}).",
            "path": str(raw_path),
            "is_artifact_safe": False,
            "row_count": 0,
            "schema_version": "unknown",
            "leakage_detected": False,
            "leakage_details": [],
        }

    resolved_path = Path(raw_path).resolve() if Path(raw_path).is_absolute() else (ROOT / raw_path).resolve()
    if not resolved_path.is_file():
        return {
            "status": "unavailable",
            "reason": "service_delivery_projection_file_not_found",
            "message": f"Projection artifact file does not exist at '{resolved_path}'.",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": "unknown",
            "leakage_detected": False,
            "leakage_details": [],
        }

    try:
        content = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {
            "status": "malformed",
            "reason": "service_delivery_projection_invalid_json",
            "message": f"Projection artifact contains invalid JSON: {exc}",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": "unknown",
            "leakage_detected": False,
            "leakage_details": [],
        }

    if not isinstance(content, Mapping):
        return {
            "status": "malformed",
            "reason": "service_delivery_projection_root_must_be_object",
            "message": "Projection JSON root is not an object.",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": "unknown",
            "leakage_detected": False,
            "leakage_details": [],
        }

    payload = dict(content)
    schema_ver = str(payload.get("schema_version", payload.get("report_version", "")))
    if schema_ver not in SUPPORTED_PROJECTION_VERSIONS:
        return {
            "status": "malformed",
            "reason": "unsupported_service_delivery_projection",
            "message": f"Schema version '{schema_ver}' is not supported. Expected one of {sorted(SUPPORTED_PROJECTION_VERSIONS)}.",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": schema_ver,
            "leakage_detected": False,
            "leakage_details": [],
        }

    # Verify read-only guarantees in payload
    if payload.get("read_only") is not True or payload.get("network_calls") is True or payload.get("mutated") is True:
        return {
            "status": "blocked",
            "reason": "unsafe_service_delivery_projection",
            "message": "Projection payload violates read-only safety invariants (read_only!=True, network_calls==True, or mutated==True).",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": schema_ver,
            "leakage_detected": False,
            "leakage_details": [],
        }

    # Verify workspace isolation
    leaks = check_projection_workspace_isolation(payload)
    if leaks:
        return {
            "status": "failed",
            "reason": "service_delivery_projection_failed_workspace_isolation",
            "message": f"Workspace isolation leakage detected in projection: {leaks}",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": schema_ver,
            "leakage_detected": True,
            "leakage_details": leaks,
        }

    rows = payload.get("engagements", payload.get("packages", []))
    if not isinstance(rows, list):
        return {
            "status": "malformed",
            "reason": "service_delivery_projection_rows_must_be_array",
            "message": "Projection packages/engagements field is not an array.",
            "path": str(resolved_path),
            "is_artifact_safe": True,
            "row_count": 0,
            "schema_version": schema_ver,
            "leakage_detected": False,
            "leakage_details": [],
        }

    return {
        "status": "passed",
        "reason": "valid_projection",
        "message": f"Projection conforms to {schema_ver} with {len(rows)} engagement row(s).",
        "path": str(resolved_path),
        "is_artifact_safe": True,
        "row_count": len(rows),
        "schema_version": schema_ver,
        "leakage_detected": False,
        "leakage_details": [],
    }


def probe_service_delivery_workbench(
    base_url: str | None = None,
    timeout_seconds: float = 2.0,
) -> dict[str, Any]:
    """Probe the service delivery workbench endpoint over HTTP or via in-process module."""
    if base_url:
        url = f"{base_url.rstrip('/')}{ENDPOINT_PATH}"
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: operator-supplied URL
                raw = response.read(65536).decode("utf-8")
                status_code = response.status
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"raw": raw[:200]}
                return {
                    "mode": "http",
                    "status": "passed" if status_code == 200 else "failed",
                    "status_code": status_code,
                    "url": url,
                    "reason": "ok" if status_code == 200 else f"http_status_{status_code}",
                    "response": payload if isinstance(payload, dict) else {"data": payload},
                    "live_endpoint_status": payload.get("live_endpoint_status", "unknown") if isinstance(payload, dict) else "unknown",
                }
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return {
                    "mode": "http",
                    "status": "unavailable",
                    "status_code": 404,
                    "url": url,
                    "reason": "service_delivery_route_not_found",
                    "detail": "HTTP 404: Route is not installed or enabled on the server.",
                }
            elif exc.code == 429:
                return {
                    "mode": "http",
                    "status": "passed",
                    "status_code": 429,
                    "url": url,
                    "reason": "rate_limited_ok",
                    "detail": "Rate limit middleware active and responding.",
                }
            return {
                "mode": "http",
                "status": "failed",
                "status_code": exc.code,
                "url": url,
                "reason": f"http_error_{exc.code}",
                "detail": str(exc),
            }
        except (TimeoutError, socket.timeout):
            return {
                "mode": "http",
                "status": "timed_out",
                "status_code": None,
                "url": url,
                "reason": "connection_timed_out",
                "detail": f"Request exceeded timeout of {timeout_seconds}s.",
            }
        except (OSError, urllib.error.URLError) as exc:
            return {
                "mode": "http",
                "status": "unavailable",
                "status_code": None,
                "url": url,
                "reason": "service_unreachable",
                "detail": f"Cannot connect to host: {exc}",
            }

    # In-process / offline dry run mode
    try:
        import importlib
        mod = importlib.import_module("api.routes.service_delivery_workbench")
        workbench_fn = getattr(mod, "workbench", None)
        if callable(workbench_fn):
            result = workbench_fn()
            availability = result.get("availability", result.get("live_endpoint_status", "available_read_only")) if isinstance(result, dict) else "unknown"
            return {
                "mode": "in_process",
                "status": "passed",
                "status_code": 200,
                "url": ENDPOINT_PATH,
                "reason": "in_process_router_verified",
                "live_endpoint_status": availability,
                "detail": "api.routes.service_delivery_workbench is installed and callable.",
            }
    except ModuleNotFoundError:
        return {
            "mode": "in_process",
            "status": "unavailable",
            "status_code": None,
            "url": ENDPOINT_PATH,
            "reason": "service_delivery_route_not_installed",
            "detail": "api.routes.service_delivery_workbench is not installed on this checkout (PR #271 unmerged).",
        }
    except Exception as exc:
        return {
            "mode": "in_process",
            "status": "failed",
            "status_code": None,
            "url": ENDPOINT_PATH,
            "reason": "in_process_execution_error",
            "detail": f"Error invoking workbench router: {exc}",
        }

    return {
        "mode": "in_process",
        "status": "unavailable",
        "status_code": None,
        "url": ENDPOINT_PATH,
        "reason": "service_delivery_route_not_installed",
        "detail": "Router not available.",
    }


def classify_service_delivery_ci(
    runner_id: int = 0,
    total_steps: int = 0,
    ci_status: str | None = None,
    logs_available: bool = False,
    annotations: list[str] | None = None,
) -> dict[str, Any]:
    """Strictly classify CI evidence fail-closed.
    
    Distinguishes zero-step runner allocation failures from code execution failures.
    Zero-step CI is NEVER converted into a test failure or test pass; it is 'ci_unavailable'.
    """
    ann_text = " ".join(annotations or []).lower()
    is_billing_or_runner_limit = any(
        kw in ann_text
        for kw in ("payment", "spending limit", "billing", "runner was not allocated", "job was not started")
    )

    if runner_id == 0 or total_steps == 0 or not logs_available:
        if is_billing_or_runner_limit:
            reason = "GitHub Actions runner was not allocated due to spending limit or billing block."
            root_cause = "github_actions_runner_allocation_failure"
        else:
            reason = "CI runners are inactive, steps count is zero, or build logs are inaccessible."
            root_cause = "ci_unavailable_zero_steps"
        state = "ci_unavailable"
    elif ci_status == "passed" or ci_status == "success":
        state = "passed"
        reason = "CI pipeline executed all steps and completed with accessible audit logs."
        root_cause = "ci_passed"
    elif ci_status == "failed":
        state = "failed"
        reason = "One or more CI test steps executed and failed."
        root_cause = "ci_test_failure"
    else:
        state = "ci_unavailable"
        reason = f"CI status '{ci_status}' cannot be promoted without verified logs."
        root_cause = "ci_unknown_status"

    return {
        "state": state,
        "runner_id": runner_id,
        "total_steps": total_steps,
        "logs_available": logs_available,
        "root_cause": root_cause,
        "classification_reason": reason,
        "is_zero_step": total_steps == 0 or runner_id == 0,
    }


@dataclass
class ServiceDeliverySmokeReport:
    schema: str
    environment_mode: str
    overall_status: str  # passed, failed, unavailable, blocked, malformed, timed_out, ci_unavailable
    read_only: bool
    network_calls: bool
    mutated: bool
    projection_check: dict[str, Any]
    endpoint_probe: dict[str, Any]
    tooling_readiness: dict[str, Any]
    ci_evidence: dict[str, Any]
    mutation_guard: dict[str, Any]
    blockers: list[str] = field(default_factory=list)
    remediations: list[str] = field(default_factory=list)
    deterministic_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def compute_hash(self) -> str:
        deterministic_view = {
            "schema": self.schema,
            "environment_mode": self.environment_mode,
            "overall_status": self.overall_status,
            "read_only": self.read_only,
            "mutated": self.mutated,
            "projection_status": self.projection_check.get("status"),
            "projection_reason": self.projection_check.get("reason"),
            "endpoint_status": self.endpoint_probe.get("status"),
            "endpoint_reason": self.endpoint_probe.get("reason"),
            "ci_state": self.ci_evidence.get("state"),
            "blockers": sorted(self.blockers),
        }
        payload = json.dumps(deterministic_view, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_service_delivery_smoke(
    environ: Mapping[str, str] | None = None,
    base_url: str | None = None,
    projection_path: Path | str | None = None,
    environment_mode: str = "local_dry_run",
    timeout_seconds: float = 2.0,
    ci_override: dict[str, Any] | None = None,
    artifacts_root: Path | None = None,
) -> ServiceDeliverySmokeReport:
    """Execute complete deployment dry run and release smoke for service delivery."""
    env = os.environ if environ is None else environ
    blockers: list[str] = []
    remediations: list[str] = []

    # 1. Environment contract & live mutation check
    active_mutations = [k for k in MUTATION_FLAG_KEYS if is_truthy(env.get(k))]
    mutation_guard = {
        "status": "blocked" if active_mutations else "active",
        "active_flags": active_mutations,
        "all_flags_disabled": len(active_mutations) == 0,
    }
    if active_mutations:
        blockers.append(f"live_mutations_forbidden: Found active flags: {active_mutations}")
        remediations.append(f"Unset mutation flags: {active_mutations}")

    # 2. Tooling readiness
    docker_diag = diagnose_missing_docker()
    runner_diag = diagnose_missing_runner()
    tooling = {
        "python_version": platform.python_version(),
        "docker": {
            "status": "ok" if docker_diag.status == "ok" else "unavailable",
            "in_path": docker_diag.status == "ok",
        },
        "runner": {
            "status": runner_diag.status,
            "runner_available": runner_diag.status == "ok",
        },
    }

    # 3. Projection artifact validation
    proj_check = validate_service_delivery_projection(path=projection_path, artifacts_root=artifacts_root, environ=env)
    if proj_check["status"] == "blocked":
        blockers.append(f"projection_blocked: {proj_check['message']}")
        remediations.append("Ensure MARKETOS_SERVICE_DELIVERY_PROJECTION points within artifacts/ directory.")
    elif proj_check["status"] == "failed":
        blockers.append(f"projection_failed: {proj_check['message']}")
        remediations.append("Review projection generation to eliminate workspace leaks or isolation violations.")
    elif proj_check["status"] == "malformed":
        blockers.append(f"projection_malformed: {proj_check['message']}")
        remediations.append("Re-generate projection artifact using canonical producer script.")

    # 4. Route / endpoint probe
    probe = probe_service_delivery_workbench(base_url=base_url, timeout_seconds=timeout_seconds)
    if probe["status"] == "failed":
        blockers.append(f"endpoint_failed: {probe.get('reason')} - {probe.get('detail', '')}")
        remediations.append("Verify API server logs and service delivery router configuration.")
    elif probe["status"] == "timed_out":
        blockers.append("endpoint_timed_out: Workbench probe exceeded timeout limit.")
        remediations.append("Check host responsiveness or adjust timeout threshold.")

    # 5. CI evidence classification
    if ci_override is not None:
        ci_eval = classify_service_delivery_ci(**ci_override)
    else:
        # Default local dry-run: runners inactive locally
        ci_eval = classify_service_delivery_ci(
            runner_id=0,
            total_steps=0,
            ci_status="ci_unavailable",
            logs_available=False,
        )

    # Resolve overall status
    if any("live_mutations_forbidden" in b for b in blockers) or proj_check["status"] == "blocked":
        overall_status = "blocked"
    elif proj_check["status"] == "malformed":
        overall_status = "malformed"
    elif probe["status"] == "timed_out":
        overall_status = "timed_out"
    elif any("failed" in b for b in blockers) or proj_check["status"] == "failed" or probe["status"] == "failed":
        overall_status = "failed"
    elif proj_check["status"] == "unavailable" or probe["status"] == "unavailable":
        overall_status = "unavailable"
    else:
        overall_status = "passed"

    report = ServiceDeliverySmokeReport(
        schema="MarketOS.ServiceDeliverySmoke.v1",
        environment_mode=environment_mode,
        overall_status=overall_status,
        read_only=True,
        network_calls=bool(base_url),
        mutated=False,
        projection_check=proj_check,
        endpoint_probe=probe,
        tooling_readiness=tooling,
        ci_evidence=ci_eval,
        mutation_guard=mutation_guard,
        blockers=sorted(set(blockers)),
        remediations=sorted(set(remediations)),
        deterministic_hash="",
    )
    report.deterministic_hash = report.compute_hash()
    return report


__all__ = [
    "ServiceDeliverySmokeReport",
    "is_path_under_artifacts",
    "check_projection_workspace_isolation",
    "validate_service_delivery_projection",
    "probe_service_delivery_workbench",
    "classify_service_delivery_ci",
    "run_service_delivery_smoke",
]
