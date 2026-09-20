"""scripts/run_service_delivery_dry_run.py -- CLI driver for MarketOS Service Delivery

Deployment Dry-Run and Release-Smoke validation.

Usage:
  python scripts/run_service_delivery_dry_run.py --json
  python scripts/run_service_delivery_dry_run.py --summary
  python scripts/run_service_delivery_dry_run.py --base-url http://127.0.0.1:3000 --json
  python scripts/run_service_delivery_dry_run.py --projection-path artifacts/service_delivery_projection.json --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.deployment.service_delivery_smoke import (
    is_path_under_artifacts,
    run_service_delivery_smoke,
)

ARTIFACTS_DIR = (ROOT / "artifacts").resolve()


def render_summary(report_dict: dict) -> str:
    lines = [
        "============================================================",
        " MarketOS Service Delivery Deployment Dry-Run & Smoke Check",
        "============================================================",
        f"Environment Mode : {report_dict.get('environment_mode')}",
        f"Overall Status   : {report_dict.get('overall_status')}",
        f"Read-Only Safe   : {report_dict.get('read_only')}",
        f"Mutated          : {report_dict.get('mutated')}",
        f"Network Calls    : {report_dict.get('network_calls')}",
        f"Deterministic SHA: {report_dict.get('deterministic_hash')[:16]}...",
        "",
        "--- Component Checks ---",
    ]

    proj = report_dict.get("projection_check", {})
    lines.append(f"Projection Artifact : [{proj.get('status', 'unknown').upper()}] {proj.get('reason', '')}")
    if proj.get("path"):
        lines.append(f"  Path              : {proj.get('path')}")
        lines.append(f"  Schema Version    : {proj.get('schema_version')}")
        lines.append(f"  Rows              : {proj.get('row_count')}")

    probe = report_dict.get("endpoint_probe", {})
    lines.append(f"Workbench Endpoint  : [{probe.get('status', 'unknown').upper()}] {probe.get('reason', '')}")
    lines.append(f"  Mode              : {probe.get('mode')}")
    if probe.get("url"):
        lines.append(f"  Target URL        : {probe.get('url')}")
    if probe.get("detail"):
        lines.append(f"  Detail            : {probe.get('detail')}")

    tooling = report_dict.get("tooling_readiness", {})
    docker = tooling.get("docker", {})
    lines.append(f"Container Runtime   : [{docker.get('status', 'unknown').upper()}] Docker in path: {docker.get('in_path')}")
    runner = tooling.get("runner", {})
    lines.append(f"Execution Runner    : [{runner.get('status', 'unknown').upper()}] Available: {runner.get('runner_available')}")

    ci = report_dict.get("ci_evidence", {})
    lines.append(f"CI Evidence State   : [{ci.get('state', 'unknown').upper()}] {ci.get('root_cause', '')}")
    lines.append(f"  Reason            : {ci.get('classification_reason')}")

    guard = report_dict.get("mutation_guard", {})
    lines.append(f"Mutation Guard      : [{guard.get('status', 'unknown').upper()}] All flags disabled: {guard.get('all_flags_disabled')}")

    blockers = report_dict.get("blockers", [])
    if blockers:
        lines.append("")
        lines.append("--- Blockers Detected ---")
        for b in blockers:
            lines.append(f"  * {b}")

    remediations = report_dict.get("remediations", [])
    if remediations:
        lines.append("")
        lines.append("--- Actionable Remediations ---")
        for r in remediations:
            lines.append(f"  * {r}")

    lines.append("============================================================")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MarketOS Service Delivery Deployment Dry-Run and Smoke Check",
    )
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--json", action="store_true", help="Output machine-readable JSON (default)")
    output_group.add_argument("--summary", action="store_true", help="Output human-readable summary")
    parser.add_argument("--base-url", type=str, default=None, help="Optional local backend URL; only localhost/loopback is permitted")
    parser.add_argument("--projection-path", type=str, default=None, help="Path to service delivery projection JSON")
    parser.add_argument("--env-mode", type=str, default="local_dry_run", help="Deployment environment mode")
    parser.add_argument("--timeout", type=float, default=2.0, help="Endpoint probe timeout in seconds")
    parser.add_argument("--output", type=str, default=None, help="Save report to path under artifacts/")
    
    # CI classification testing options
    parser.add_argument("--ci-status", type=str, default=None, help="CI pipeline status string")
    parser.add_argument("--ci-steps", type=int, default=0, help="Number of executed CI steps")
    parser.add_argument("--ci-runner-id", type=int, default=0, help="Runner ID allocated by CI")
    parser.add_argument("--ci-logs", action="store_true", default=False, help="Whether build logs are accessible")
    parser.add_argument("--ci-annotation", type=str, default=None, help="Optional annotation or error message from CI")

    args = parser.parse_args(argv)

    ci_override = None
    if args.ci_status is not None or args.ci_steps > 0 or args.ci_runner_id > 0:
        ci_override = {
            "runner_id": args.ci_runner_id,
            "total_steps": args.ci_steps,
            "ci_status": args.ci_status,
            "logs_available": args.ci_logs,
            "annotations": [args.ci_annotation] if args.ci_annotation else None,
        }

    report = run_service_delivery_smoke(
        base_url=args.base_url,
        projection_path=args.projection_path,
        environment_mode=args.env_mode,
        timeout_seconds=args.timeout,
        ci_override=ci_override,
    )
    report_dict = report.to_dict()

    if args.output:
        out_path = Path(args.output)
        if not is_path_under_artifacts(out_path):
            print(f"Error: --output path '{args.output}' must resolve under artifacts/ directory.", file=sys.stderr)
            return 1
        resolved_out = out_path.resolve() if out_path.is_absolute() else (ROOT / out_path).resolve()
        resolved_out.parent.mkdir(parents=True, exist_ok=True)
        resolved_out.write_text(json.dumps(report_dict, indent=2) + "\n", encoding="utf-8")

    if args.json or not args.summary:
        print(json.dumps(report_dict, indent=2))
    else:
        print(render_summary(report_dict))

    # Exit code: 0 if passed or unavailable (clean offline notice); 1 if failed, blocked, malformed, or timed_out
    if report.overall_status in {"failed", "blocked", "malformed", "timed_out"}:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
