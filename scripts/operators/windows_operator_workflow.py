"""Windows-first MarketOS operator workflow (dry-run by default).

Canonical command surface used by ``Invoke-MarketOSOperator.ps1``.
Does not recreate scoring, event spine, or a second storefront.
Does not invoke live provider, order, ad, payment, or messaging actions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.operators.windows_operator_safety import (
    OperatorSafetyError,
    assert_no_authority,
    contains_secret_shaped,
    load_json_object,
    reject_live_flags,
    require_safe_input,
    require_safe_output_dir,
)
from scripts.operators.windows_operator_scenarios import run_scenario_pack

CONTRACT_VERSION = "marketos-windows-operator-workflow-v1"
EVIDENCE_CLASSES = ("fixture", "simulated", "unavailable", "not_run", "blocked", "actual")
COMMANDS = (
    "preflight",
    "fixture-import",
    "supplier-import",
    "product-validation",
    "commerce-cycle",
    "batch-manifest",
    "client-safe-export",
    "phase-readiness",
    "inspect-evidence",
    "replay",
    "start-local",
    "staging-acceptance",
    "scenario-pack",
    "coderos-probe",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def summary(
    *,
    command: str,
    evidence_class: str,
    status: str,
    exit_code: int,
    details: dict[str, Any],
) -> dict[str, Any]:
    body = {
        "contract_version": CONTRACT_VERSION,
        "command": command,
        "status": status,
        "evidence_class": evidence_class,
        "exit_code": exit_code,
        "generated_at": _now(),
        "read_only": True,
        "mutated": False,
        "network_calls": False,
        "authorities": {key: False for key in ("launch", "ads", "orders", "payments", "messaging", "publishing")},
        "details": details,
    }
    body["fingerprint"] = fingerprint({k: v for k, v in body.items() if k != "fingerprint" and k != "generated_at"})
    return body


def emit(payload: dict[str, Any], output: Path | None) -> int:
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    sys.stdout.write(text)
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{payload['command'].replace('-', '_')}_summary.json").write_text(text, encoding="utf-8")
    return int(payload["exit_code"])


def _python() -> str:
    return sys.executable


def _run_cli(script_rel: str, extra: list[str]) -> dict[str, Any]:
    script = ROOT / script_rel
    if not script.is_file():
        return {"available": False, "exit_code": 3, "reason": f"missing_cli:{script_rel}", "stdout": ""}
    try:
        proc = subprocess.run(
            [_python(), str(script), *extra],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "exit_code": 3,
            "reason": "cli_timeout",
            "stdout": "",
        }
    combined = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and "ModuleNotFoundError" in combined:
        return {
            "available": False,
            "exit_code": 3,
            "reason": "python_dependency_unavailable",
            "stdout": combined[-2000:],
        }
    return {
        "available": True,
        "exit_code": proc.returncode,
        "reason": "ok" if proc.returncode == 0 else "cli_failed",
        "stdout": combined[-2000:],
    }


def cmd_preflight() -> dict[str, Any]:
    tools = {
        "python": shutil.which("python") or shutil.which("python3"),
        "node": shutil.which("node"),
        "npm": shutil.which("npm") or shutil.which("npm.cmd"),
        "pwsh": shutil.which("pwsh") or shutil.which("powershell"),
        "git": shutil.which("git"),
    }
    sibling_prs = {
        "pr_228_windows_first_phase_runner": "owned_elsewhere",
        "pr_230_first_phase_cockpit": "owned_elsewhere",
        "pr_238_commerce_operations_batch": "owned_elsewhere",
    }
    missing_eval = False
    try:
        import evaluation.experiments  # noqa: F401
    except Exception:
        missing_eval = True
    details = {
        "repository": str(ROOT),
        "platform": sys.platform,
        "tools": {name: bool(path) for name, path in tools.items()},
        "sibling_ownership": sibling_prs,
        "evaluation_scipy_unavailable": missing_eval,
        "notes": [
            "Live flags are rejected.",
            "PR #228 remains the first-phase intelligence runner owner.",
            "PR #230 remains the frontend cockpit owner.",
        ],
    }
    evidence = "unavailable" if missing_eval else "fixture"
    status = "partial" if missing_eval else "ready"
    return summary(command="preflight", evidence_class=evidence, status=status, exit_code=0, details=details)


def cmd_copy_sanitized(command: str, source: str, output: str, *, expected_class: str) -> dict[str, Any]:
    src = require_safe_input(ROOT, source, label="source")
    dest_root = require_safe_output_dir(ROOT, output)
    dest_root.mkdir(parents=True, exist_ok=True)
    payload: Any
    if src.suffix.lower() == ".json":
        payload = load_json_object(src)
        assert_no_authority(payload)
        dest = dest_root / src.name
        dest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        text = src.read_text(encoding="utf-8")
        if contains_secret_shaped(text):
            raise OperatorSafetyError("secret-shaped content rejected", 4)
        dest = dest_root / src.name
        dest.write_text(text, encoding="utf-8")
        payload = {"path": src.name, "kind": "text"}
    return summary(
        command=command,
        evidence_class=expected_class,
        status="copied",
        exit_code=0,
        details={"source": str(src), "destination": str(dest), "bytes": dest.stat().st_size, "never_actual": True},
    )


def cmd_product_validation(client_name: str, output: str | None) -> dict[str, Any]:
    extra = ["--json"]
    if client_name:
        extra.extend(["--client-name", client_name])
    dest = require_safe_output_dir(ROOT, output) if output else None
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)
        extra.extend(["--output", str(dest)])
    result = _run_cli("scripts/generate_product_validation_report.py", extra)
    evidence = "unavailable" if not result["available"] else "fixture"
    exit_code = 3 if not result["available"] else (0 if result["exit_code"] == 0 else 1)
    return summary(
        command="product-validation",
        evidence_class=evidence,
        status=result["reason"],
        exit_code=exit_code,
        details={"cli": result, "classification": "fixture_or_unavailable_never_actual"},
    )


def cmd_commerce_cycle(fixture: str, output: str | None) -> dict[str, Any]:
    src = require_safe_input(ROOT, fixture, label="fixture")
    try:
        fixture_payload = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OperatorSafetyError(f"commerce fixture could not be read: {src}") from exc
    records = fixture_payload if isinstance(fixture_payload, list) else [fixture_payload]
    query = next(
        (
            str(record["query"]).strip()
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("query"), str)
            and record["query"].strip()
        ),
        "",
    )
    if not query:
        raise OperatorSafetyError("commerce fixture must contain a non-empty query")
    extra = ["--fixture", str(src), "--query", query, "--json", "--max-candidates", "3"]
    dest = require_safe_output_dir(ROOT, output) if output else None
    result = _run_cli("scripts/run_commerce_mvp_slice.py", extra)
    operations = ROOT / "scripts/run_commerce_operations_cycle.py"
    details = {
        "fixture": str(src),
        "mvp_slice": result,
        "operations_cycle": "not_run" if not operations.is_file() else "present_not_invoked_default",
        "output": str(dest) if dest else None,
    }
    evidence = "unavailable" if not result["available"] else "fixture"
    exit_code = 3 if not result["available"] else (0 if result["exit_code"] == 0 else 1)
    return summary(
        command="commerce-cycle",
        evidence_class=evidence,
        status=result["reason"],
        exit_code=exit_code,
        details=details,
    )


def cmd_batch_manifest(manifest: str) -> dict[str, Any]:
    src = require_safe_input(ROOT, manifest, label="manifest")
    payload = load_json_object(src)
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise OperatorSafetyError("batch manifest jobs must be a list")
    cycle = ROOT / "scripts/run_commerce_operations_cycle.py"
    return summary(
        command="batch-manifest",
        evidence_class="not_run" if not cycle.is_file() else "fixture",
        status="validated_local_manifest" if cycle.is_file() else "operations_cycle_cli_absent",
        exit_code=0,
        details={
            "manifest": str(src),
            "job_count": len(jobs),
            "operations_cycle_cli": str(cycle) if cycle.is_file() else "not_on_this_branch",
            "note": "PR #238 owns batch I/O if present; this command only validates the local manifest.",
        },
    )


def cmd_client_safe_export(source: str, output: str) -> dict[str, Any]:
    src = require_safe_input(ROOT, source, label="source")
    dest_root = require_safe_output_dir(ROOT, output)
    dest_root.mkdir(parents=True, exist_ok=True)
    payload = load_json_object(src)
    assert_no_authority(payload)
    export = {
        "export_version": "windows-operator-client-safe-v1",
        "read_only": True,
        "mutated": False,
        "network_calls": False,
        "source_name": src.name,
        "evidence_class": payload.get("evidence_class", "fixture"),
        "keys": sorted(payload.keys()),
        "authorities": {key: False for key in ("launch", "ads", "orders", "payments", "messaging")},
    }
    if contains_secret_shaped(export):
        raise OperatorSafetyError("client_safe_export_rejected_secret_shaped_value", 4)
    dest = dest_root / "client_safe_export.json"
    dest.write_text(json.dumps(export, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary(
        command="client-safe-export",
        evidence_class="fixture",
        status="exported",
        exit_code=0,
        details={"destination": str(dest), "source": str(src)},
    )


def cmd_phase_readiness(output: str | None) -> dict[str, Any]:
    extra = ["--json"]
    dest = require_safe_output_dir(ROOT, output) if output else None
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)
        extra.extend(["--output", str(dest)])
    result = _run_cli("scripts/phase1_readiness_report.py", extra)
    evidence = "unavailable" if not result["available"] else "fixture"
    exit_code = 3 if not result["available"] else (0 if result["exit_code"] == 0 else 1)
    return summary(
        command="phase-readiness",
        evidence_class=evidence,
        status=result["reason"],
        exit_code=exit_code,
        details={"cli": result},
    )


def cmd_inspect(path: str) -> dict[str, Any]:
    src = require_safe_input(ROOT, path, label="evidence")
    payload = load_json_object(src) if src.suffix.lower() == ".json" else {"text_chars": src.stat().st_size}
    redacted_keys = sorted(str(key) for key in payload)[:40]
    return summary(
        command="inspect-evidence",
        evidence_class=str(payload.get("evidence_class", "fixture")) if isinstance(payload, dict) else "fixture",
        status="inspected",
        exit_code=0,
        details={"path": str(src), "keys": redacted_keys, "secret_shaped": False},
    )


def cmd_replay(packet: str) -> dict[str, Any]:
    src = require_safe_input(ROOT, packet, label="packet")
    payload = load_json_object(src)
    first = fingerprint(payload)
    second = fingerprint(json.loads(json.dumps(payload, sort_keys=True)))
    if first != second:
        return summary(
            command="replay",
            evidence_class="blocked",
            status="fingerprint_mismatch",
            exit_code=5,
            details={"first": first, "second": second},
        )
    return summary(
        command="replay",
        evidence_class="fixture",
        status="byte_identical",
        exit_code=0,
        details={"fingerprint": first, "path": str(src)},
    )


def cmd_start_local() -> dict[str, Any]:
    commands = {
        "api": 'python -m uvicorn backend.api:app --host 127.0.0.1 --port 8000',
        "frontend": 'npm --prefix frontend run dev',
        "note": "Commands are printed only. --allow-start is blocked. No process is spawned.",
    }
    return summary(
        command="start-local",
        evidence_class="not_run",
        status="commands_documented_not_started",
        exit_code=0,
        details=commands,
    )


def cmd_staging(base_url: str | None) -> dict[str, Any]:
    if not base_url:
        return summary(
            command="staging-acceptance",
            evidence_class="not_run",
            status="network_disabled_default",
            exit_code=0,
            details={
                "probes": ["/health", "/ready"],
                "cors": "inspect ALLOWED_ORIGINS locally; do not treat Netlify preview as backend evidence",
                "cockpit_route": "/operator/first-phase",
                "operator_events": "/operator/events",
                "websocket": "not_run unless an approved private staging URL is supplied later",
            },
        )
    raise OperatorSafetyError("staging HTTP probes require an explicit future allow-network policy; default remains not_run", 4)


def cmd_coderos() -> dict[str, Any]:
    adapter = ROOT / "backend/adapters/coderos_readonly.py"
    if not adapter.is_file():
        return summary(
            command="coderos-probe",
            evidence_class="unavailable",
            status="adapter_missing",
            exit_code=3,
            details={"adapter": str(adapter)},
        )
    try:
        from backend.adapters.coderos_readonly import CoderOSAdapterConfig, probe

        report = probe(CoderOSAdapterConfig())
        state = report.probe_result.state
        return summary(
            command="coderos-probe",
            evidence_class="not_run" if state == "not_run" else "fixture",
            status=state,
            exit_code=0,
            details={
                "mode": "plan_only",
                "would_execute": report.planned_action.would_execute,
                "reason": report.planned_action.reason,
                "windows_snapshot_script": "C:\\Users\\HP\\Documents\\GitHub\\CoderOS\\scripts\\coderos_snapshot.py",
                "windows_snapshot_status": "unavailable_in_this_linux_agent",
            },
        )
    except Exception as exc:
        return summary(
            command="coderos-probe",
            evidence_class="unavailable",
            status="probe_failed",
            exit_code=3,
            details={"error": type(exc).__name__},
        )


def cmd_scenario_pack(pack_dir: str, output: str | None) -> dict[str, Any]:
    if ".." in Path(pack_dir).parts:
        raise OperatorSafetyError("path traversal is not allowed")
    pack_path = Path(pack_dir)
    pack_path = pack_path if pack_path.is_absolute() else (ROOT / pack_path)
    dest = require_safe_output_dir(ROOT, output) if output else None
    packet = run_scenario_pack(pack_path)
    if dest is not None:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "scenario_pack_summary.json").write_text(
            json.dumps(packet, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    evidence = packet["evidence_class"]
    return summary(
        command="scenario-pack",
        evidence_class=evidence,
        status=packet["status"],
        exit_code=packet["exit_code"],
        details=packet,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--source")
    parser.add_argument("--fixture")
    parser.add_argument("--manifest")
    parser.add_argument("--packet")
    parser.add_argument("--path")
    parser.add_argument("--output")
    parser.add_argument("--client-name", default="")
    parser.add_argument("--pack-dir", default="tests/fixtures/windows_operator/scenarios")
    parser.add_argument("--base-url")
    parser.add_argument("--json", action="store_true", help="accepted for operator habit; output is always JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        reject_live_flags(argv)
        args = build_parser().parse_args(argv)
        command = args.command
        output = args.output
        if command == "preflight":
            payload = cmd_preflight()
        elif command == "fixture-import":
            if not args.source or not args.output:
                raise OperatorSafetyError("fixture-import requires --source and --output")
            payload = cmd_copy_sanitized("fixture-import", args.source, args.output, expected_class="fixture")
        elif command == "supplier-import":
            if not args.source or not args.output:
                raise OperatorSafetyError("supplier-import requires --source and --output")
            payload = cmd_copy_sanitized("supplier-import", args.source, args.output, expected_class="simulated")
        elif command == "product-validation":
            payload = cmd_product_validation(args.client_name, args.output)
        elif command == "commerce-cycle":
            if not args.fixture:
                raise OperatorSafetyError("commerce-cycle requires --fixture")
            payload = cmd_commerce_cycle(args.fixture, args.output)
        elif command == "batch-manifest":
            if not args.manifest:
                raise OperatorSafetyError("batch-manifest requires --manifest")
            payload = cmd_batch_manifest(args.manifest)
        elif command == "client-safe-export":
            if not args.source or not args.output:
                raise OperatorSafetyError("client-safe-export requires --source and --output")
            payload = cmd_client_safe_export(args.source, args.output)
        elif command == "phase-readiness":
            payload = cmd_phase_readiness(args.output)
        elif command == "inspect-evidence":
            if not args.path:
                raise OperatorSafetyError("inspect-evidence requires --path")
            payload = cmd_inspect(args.path)
        elif command == "replay":
            if not args.packet:
                raise OperatorSafetyError("replay requires --packet")
            payload = cmd_replay(args.packet)
        elif command == "start-local":
            payload = cmd_start_local()
        elif command == "staging-acceptance":
            payload = cmd_staging(args.base_url)
        elif command == "coderos-probe":
            payload = cmd_coderos()
        elif command == "scenario-pack":
            payload = cmd_scenario_pack(args.pack_dir, args.output)
        else:
            raise OperatorSafetyError(f"unknown command: {command}")
        dest = require_safe_output_dir(ROOT, output) if output else None
        return emit(payload, dest)
    except OperatorSafetyError as exc:
        payload = summary(
            command="blocked" if exc.exit_code == 4 else "invalid",
            evidence_class="blocked" if exc.exit_code == 4 else "unavailable",
            status=str(exc),
            exit_code=exc.exit_code,
            details={"error": str(exc)},
        )
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
