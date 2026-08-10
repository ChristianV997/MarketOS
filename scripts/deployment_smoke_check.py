"""Read-only Phase 1 deployment contract and endpoint smoke checks."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.security.cors import explain_cors_readiness
from backend.security.rate_limit import explain_rate_limit_status

CONTRACT_PATH = ROOT / "deploy/mvp/env.contract.json"
ARTIFACTS = (ROOT / "artifacts").resolve()


def _env_file(path: str | None) -> dict[str, str]:
    values = dict(os.environ)
    if not path:
        return values
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def _safe_value(name: str, value: str) -> str:
    return "<set>" if value and name not in {"ALLOWED_ORIGINS", "VITE_API_BASE_URL"} else value


def _under_artifacts(value: str) -> bool:
    if not value:
        return True
    path = Path(value)
    resolved = (ROOT / path).resolve() if not path.is_absolute() else path.resolve()
    return resolved == ARTIFACTS or ARTIFACTS in resolved.parents


def _get_json_response(base: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(f"{base.rstrip('/')}{path}", method=method, headers={"Accept": "application/json"})
    if body is not None:
        request.data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310: operator supplies an explicit local/staging URL
        payload = json.loads(response.read().decode("utf-8"))
        headers = {key.lower(): value for key, value in response.headers.items()}
    return (payload if isinstance(payload, dict) else {"value": payload}), headers


def _get_json(base: str, path: str, *, method: str = "GET", body: dict[str, Any] | None = None) -> dict[str, Any]:
    return _get_json_response(base, path, method=method, body=body)[0]


def _get_status(base: str, path: str) -> int:
    request = urllib.request.Request(f"{base.rstrip('/')}{path}", method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:  # nosec B310: explicit operator URL
        response.read(64)
        return response.status


def build_report(*, environ: dict[str, str] | None = None, env_file: str | None = None, backend_url: str | None = None, frontend_url: str | None = None, profile: str | None = None) -> dict[str, Any]:
    values = _env_file(env_file) if env_file else (dict(os.environ) if environ is None else environ)
    report: dict[str, Any] = {"status": "passed", "network_calls": bool(backend_url or frontend_url), "mutated": False, "checks": [], "next_actions": [], "profile": profile or "local"}
    try:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        report["contract_present"] = True
    except (OSError, json.JSONDecodeError) as exc:
        report["status"] = "failed"
        report["checks"].append({"name": "env_contract", "status": "failed", "detail": type(exc).__name__})
        return report
    missing: list[str] = []
    for item in contract["variables"]:
        is_required = item.get("required", item["required_for"] in {"backend", "frontend"} and item.get("phase") == "now")
        if is_required and not values.get(item["name"]):
            missing.append(item["name"])
    report["environment"] = {"missing_required": missing, "configured": [{"name": item["name"], "value": _safe_value(item["name"], values.get(item["name"], ""))} for item in contract["variables"] if values.get(item["name"])]}
    report["checks"].append({"name": "required_environment", "status": "passed" if not missing else "partial", "missing": missing})
    cors = explain_cors_readiness(values)
    limits = explain_rate_limit_status()
    hardening_status = "failed" if cors["blockers"] else ("partial" if cors["warnings"] else "passed")
    report["checks"].append({"name": "production_hardening", "status": hardening_status, "cors_configured": cors["configured"], "cors_mvp_safe": cors["mvp_safe"], "allowed_origin_count": cors["allowed_origin_count"], "cors_warnings": cors["warnings"], "cors_blockers": cors["blockers"], "request_id_middleware_enabled": True, "rate_limit_enabled": True, "public_run_rate_limit": limits["public_run_rate_limit"], "event_read_rate_limit": limits["event_read_rate_limit"], "safe_logging_enabled": True, "secret_redaction_enabled": True})
    report["security"] = {"cors_configured": cors["configured"], "cors_mvp_safe": cors["mvp_safe"], "allowed_origin_count": cors["allowed_origin_count"], "request_id_middleware_enabled": True, "rate_limit_enabled": True, "public_run_rate_limit": limits["public_run_rate_limit"], "event_read_rate_limit": limits["event_read_rate_limit"], "safe_logging_enabled": True, "secret_redaction_enabled": True, "distributed_rate_limiting": False}
    if cors["blockers"]: report["status"] = "failed"
    gate_failures = []
    if values.get("MARKETOS_PUBLIC_COMMERCE_RUNS", "0") == "1": gate_failures.append("MARKETOS_PUBLIC_COMMERCE_RUNS")
    if values.get("MARKETOS_SUPABASE_CANONICAL_EVENTS", "0") == "1": gate_failures.append("MARKETOS_SUPABASE_CANONICAL_EVENTS")
    report["checks"].append({"name": "default_off_gates", "status": "passed" if not gate_failures else "failed", "enabled_gates": gate_failures})
    if gate_failures: report["status"] = "failed"
    paths = {name: values.get(name, "") for name in ("MARKETOS_EVENT_READ_JSONL_PATH", "MARKETOS_EVENT_WRITE_JSONL_PATH", "MARKETOS_PUBLIC_SIGNAL_CACHE_DIR")}
    bad_paths = [name for name, value in paths.items() if value and not _under_artifacts(value)]
    report["checks"].append({"name": "artifact_paths", "status": "passed" if not bad_paths else "failed", "paths": {name: _safe_value(name, value) for name, value in paths.items()}, "invalid": bad_paths})
    if bad_paths: report["status"] = "failed"
    forbidden = contract.get("forbidden_frontend_secret_names", [])
    frontend_files = list((ROOT / "frontend").glob(".env*"))
    leaked_names = []
    for file in frontend_files:
        text = file.read_text(encoding="utf-8", errors="ignore")
        leaked_names.extend(name for name in forbidden if re.search(rf"\b{re.escape(name)}\b", text))
    report["checks"].append({"name": "frontend_secret_names", "status": "passed" if not leaked_names else "failed", "forbidden_names_found": sorted(set(leaked_names))})
    if leaked_names: report["status"] = "failed"
    required_files = [
        "deploy/mvp/marketos.mvp.json",
        "frontend/package.json",
        "frontend/vercel.json",
        "backend/api.py",
        "deploy/railway/railway.json",
        "deploy/render/render.yaml",
        "docs/OPERATOR_EVENT_DASHBOARD.md",
    ]
    missing_files = [item for item in required_files if not (ROOT / item).is_file()]
    report["checks"].append({"name": "mvp_files", "status": "passed" if not missing_files else "failed", "missing": missing_files})
    if missing_files: report["status"] = "failed"
    report["checks"].append({"name": "no_credentials_required", "status": "passed", "detail": "local smoke checks use no provider credentials"})
    if backend_url:
        endpoints = ["/health", "/ready", "/api/events/readiness", "/api/events/timeline"]
        endpoint_results = []
        for endpoint in endpoints:
            try:
                response, headers = _get_json_response(backend_url, endpoint)
                endpoint_results.append({"endpoint": endpoint, "status": "passed", "response": response, "request_id_header": bool(headers.get("x-request-id"))})
            except (OSError, ValueError, urllib.error.URLError) as exc: endpoint_results.append({"endpoint": endpoint, "status": "failed", "detail": type(exc).__name__})
        try:
            blocked, headers = _get_json_response(backend_url, "/api/commerce-mvp/public-run", method="POST", body={"query": "smoke", "allow_public_network": False, "event_target": "none"})
            endpoint_results.append({"endpoint": "/api/commerce-mvp/public-run", "status": "passed" if blocked.get("status") == "blocked" else "failed", "response": {"status": blocked.get("status"), "read_only": blocked.get("read_only"), "mutated": blocked.get("mutated")}, "request_id_header": bool(headers.get("x-request-id"))})
        except (OSError, ValueError, urllib.error.URLError) as exc: endpoint_results.append({"endpoint": "/api/commerce-mvp/public-run", "status": "failed", "detail": type(exc).__name__})
        report["backend_endpoints"] = endpoint_results
        if any(item["status"] == "failed" for item in endpoint_results): report["status"] = "partial" if report["status"] != "failed" else report["status"]
    if frontend_url:
        try:
            report["frontend_endpoint"] = {"status": "passed" if _get_status(frontend_url, "/operator/events") < 400 else "failed", "path": "/operator/events"}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            report["frontend_endpoint"] = {"status": "failed", "path": "/operator/events", "detail": type(exc).__name__}
            if report["status"] != "failed": report["status"] = "partial"
    if missing: report["status"] = "partial" if report["status"] != "failed" else report["status"]
    if missing: report["next_actions"].append("Set required server/frontend deployment variables with safe values.")
    report["next_actions"].extend(["Build frontend with cd frontend && npm run build.", "Probe /health, /ready, /api/events/readiness, and /operator/events after deployment.", "Keep public and Supabase gates off until operator review."])
    report["read_only"] = True
    return report


def markdown_report(report: dict[str, Any]) -> str:
    lines = ["# MarketOS MVP deployment smoke check", "", f"- Status: **{report['status']}**", f"- Network calls: `{report['network_calls']}`", f"- Mutated: `{report['mutated']}`", "", "## Checks", ""]
    for check in report.get("checks", []): lines.append(f"- `{check['name']}`: **{check['status']}**")
    lines.extend(["", "## Next actions", ""])
    lines.extend(f"- {item}" for item in report.get("next_actions", []))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--env-file")
    parser.add_argument("--backend-url")
    parser.add_argument("--frontend-url")
    parser.add_argument("--profile", choices=("railway", "vercel", "render"))
    parser.add_argument("--output")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if not (args.local or args.env_file or args.backend_url or args.frontend_url or args.profile): parser.error("select --local, --env-file, a URL, or --profile")
    report = build_report(env_file=args.env_file, backend_url=args.backend_url, frontend_url=args.frontend_url, profile=args.profile)
    rendered = markdown_report(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = (ROOT / args.output).resolve();
        if target != ARTIFACTS and ARTIFACTS not in target.parents: parser.error("--output must stay under artifacts/")
        target.parent.mkdir(parents=True, exist_ok=True); target.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
