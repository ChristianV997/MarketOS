#!/usr/bin/env python3
"""Run the bounded, offline Security CI Gate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.trustos.security_ci_gate import COMMAND_IDS, GATE_ACTIONS, build_security_ci_gate_report


def _input_path(value: str) -> Path:
    raw = Path(value)
    normalized = str(value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(normalized).parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if ROOT.resolve() not in path.parents and path != ROOT.resolve():
        raise ValueError("fixture path must remain inside the repository")
    if not path.is_file():
        raise ValueError("fixture path does not exist or is not a file")
    return path


def _fixture(value: str) -> tuple[dict[str, Any], str]:
    path = _input_path(value)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"fixture could not be read as JSON: {exc.__class__.__name__}") from exc
    if not isinstance(payload, dict):
        raise ValueError("fixture root must be a JSON object")
    return payload, str(path.relative_to(ROOT))


def _write_outputs(output: str, report: Any) -> None:
    directory = Path(output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        "security_ci_gate_report.json": report.to_dict(),
        "security_ci_gate_report.md": report.to_markdown(),
        "execution_plan.json": [item.to_dict() for item in report.execution_plans],
        "execution_results_sanitized.json": [item.to_dict() for item in report.execution_results],
        "normalization_results.json": [item.to_dict() for item in report.normalization_results],
        "trustos_evidence_records.json": [item.to_dict() for item in report.evidence_records],
        "trustos_gate_impacts.json": [item.to_dict() for item in report.gate_impacts],
        "redaction_report.json": [item.to_dict() for item in report.redaction_results],
        "scanner_availability.json": [item.to_dict() for item in report.availability],
    }
    for name, value in files.items():
        (directory / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n" if not isinstance(value, str) else value, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline, allowlisted Security CI Gate")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--scanner", choices=COMMAND_IDS)
    parser.add_argument("--fixture")
    parser.add_argument("--action", choices=GATE_ACTIONS)
    parser.add_argument("--run-local-scanners", action="store_true")
    parser.add_argument("--require-scanners", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        payload = None
        source_file = "fixture://security-ci-default"
        selected_scanner = args.scanner
        if args.fixture:
            payload, source_file = _fixture(args.fixture)
            if selected_scanner is None:
                stem = Path(args.fixture).stem.lower().replace("-", "_")
                selected_scanner = next((item for item in COMMAND_IDS if item.replace("_", "") in stem.replace("_", "") or item.split("_")[0] in stem), None)
                if selected_scanner is None:
                    raise ValueError("--fixture requires --scanner when the command cannot be inferred from the filename")
        report = build_security_ci_gate_report(
            command_id=selected_scanner,
            fixture_payload=payload,
            fixture_source=source_file,
            action=args.action,
            plan_only=args.plan_only,
            run_local_scanners=args.run_local_scanners,
            require_scanners=args.require_scanners,
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
