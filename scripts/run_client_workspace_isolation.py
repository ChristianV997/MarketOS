#!/usr/bin/env python3
"""Generate the offline Client Workspace Isolation Plan."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))

from evaluation.trustos.client_workspace_isolation import CLONE_TYPES, SERVICE_PACKAGES, WORKSPACE_TYPES, build_client_workspace_isolation_report


def _load(path_value: str) -> dict:
    raw = Path(path_value); normalized = str(path_value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(normalized).parts): raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if ROOT.resolve() not in path.parents and path != ROOT.resolve(): raise ValueError("fixture path must remain inside the repository")
    if not path.is_file(): raise ValueError("fixture path does not exist or is not a file")
    try: payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("fixture must be valid JSON") from exc
    if not isinstance(payload, dict): raise ValueError("fixture root must be an object")
    return payload


def _write(output: str, report) -> None:
    folder = Path(output).resolve(); folder.mkdir(parents=True, exist_ok=True); data = report.to_dict()
    files = {
        "client_workspace_isolation_report.json": data,
        "client_workspace_isolation_report.md": report.to_markdown(),
        "workspace_manifests.json": [item.to_dict() for item in report.manifests],
        "clone_manifests.json": [item.to_dict() for item in report.clone_manifests],
        "visibility_rules.json": [item.to_dict() for item in report.visibility_rules],
        "export_policies.json": [item.to_dict() for item in report.export_policies],
        "leakage_checks.json": [item.to_dict() for item in report.leakage_checks],
        "trustos_gate_results.json": [item.to_dict() for item in report.gate_results],
        "service_package_mappings.json": list(report.service_package_mappings),
    }
    for name, value in files.items():
        (folder / name).write_text(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true"); parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--workspace-type", choices=WORKSPACE_TYPES); parser.add_argument("--clone-type", choices=CLONE_TYPES)
    parser.add_argument("--service-package", choices=SERVICE_PACKAGES); parser.add_argument("--context")
    parser.add_argument("--check-leakage", action="store_true"); parser.add_argument("--output")
    args = parser.parse_args()
    if args.json and args.markdown: parser.error("choose --json or --markdown")
    try:
        payload = _load(args.context) if args.context else None
        report = build_client_workspace_isolation_report(workspace_type=args.workspace_type, clone_type=args.clone_type, service_package=args.service_package, payload=payload, check_leakage=args.check_leakage or payload is not None)
        if args.output: _write(args.output, report)
        print(report.to_markdown() if args.markdown and not args.json else json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc)); return 2


if __name__ == "__main__": raise SystemExit(main())
