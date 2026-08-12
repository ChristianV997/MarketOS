#!/usr/bin/env python3
"""Run the offline TrustOS security-scanner evidence adapter.

This command only normalizes explicitly marked fixture/output metadata. It
never invokes scanners, GitHub, or any external service.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.trustos.security_scanner_adapter import (
    GATE_ACTIONS,
    SCANNER_IDS,
    build_security_scanner_report,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _safe_input(path_value: str) -> Path:
    root = _repo_root().resolve()
    path = Path(path_value).resolve()
    if root not in path.parents and path != root:
        raise ValueError("fixture path must remain inside the repository")
    if not path.is_file():
        raise ValueError("fixture path does not exist or is not a file")
    return path


def _load_fixture(path_value: str) -> tuple[dict[str, Any], str]:
    path = _safe_input(path_value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"fixture could not be read as JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("fixture root must be a JSON object")
    return payload, str(path.relative_to(_repo_root()))


def _write_outputs(output: str, report: Any) -> None:
    directory = Path(output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "security_scanner_adapter_report.json": data,
        "security_scanner_adapter_report.md": report.to_markdown(),
        "scanner_references.json": [item.to_dict() for item in report.scanner_references],
        "normalized_findings.json": [item.to_dict() for item in report.findings],
        "trustos_evidence_records.json": [item.to_dict() for item in report.evidence_records],
        "trustos_risk_items.json": [item.to_dict() for item in report.risk_items],
        "gate_impacts.json": [item.to_dict() for item in report.gate_impacts],
        "redaction_report.json": report.redaction_policy.to_dict(),
        "scanner_integration_roadmap.json": list(report.scanner_integration_roadmap),
    }
    for name, value in files.items():
        path = directory / name
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize sanitized security scanner evidence for TrustOS")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--markdown", action="store_true", help="print Markdown")
    parser.add_argument("--scanner", choices=SCANNER_IDS)
    parser.add_argument("--fixture")
    parser.add_argument("--action", choices=GATE_ACTIONS)
    parser.add_argument("--output")
    parser.add_argument("--run-local-scanner", action="store_true", help="always rejected in v1")
    args = parser.parse_args()
    try:
        payload = None
        source_file = "fixture://security-scanner-default"
        selected_scanner = args.scanner
        if args.fixture:
            payload, source_file = _load_fixture(args.fixture)
            if selected_scanner is None:
                fixture_stem = Path(args.fixture).stem.lower()
                selected_scanner = next((item for item in SCANNER_IDS if item in fixture_stem.replace("-", "_")), None)
                if selected_scanner is None:
                    raise ValueError("--fixture requires --scanner when the scanner cannot be inferred from the filename")
        report = build_security_scanner_report(
            scanner=selected_scanner,
            payload=payload,
            source_file=source_file,
            action=args.action,
            run_local_scanner=args.run_local_scanner,
        )
        if args.output:
            _write_outputs(args.output, report)
        if args.markdown and not args.json:
            print(report.to_markdown())
        else:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
