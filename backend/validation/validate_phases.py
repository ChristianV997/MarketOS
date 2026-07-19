#!/usr/bin/env python3
"""CLI tool for running shadow-mode phase validation.

Usage:
    python -m backend.validation.validate_phases [--event-store PATH] [--output OUTPUT.json] [--phase PHASE]

Examples:
    # Validate all phases
    python -m backend.validation.validate_phases

    # Validate specific phase
    python -m backend.validation.validate_phases --phase capital_policy

    # Use custom event_store path
    python -m backend.validation.validate_phases --event-store /custom/path/events.jsonl

    # Save report to file
    python -m backend.validation.validate_phases --output validation_report.json

    # Print summary to stdout
    python -m backend.validation.validate_phases --summary
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from backend.validation.shadow_validator import (
    validate_all_phases,
    PHASE_CRITERIA,
    EventStoreReader,
)

logging.basicConfig(level=logging.INFO)
_log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Validate shadow-mode phase logic against success criteria."
    )
    parser.add_argument(
        "--event-store",
        type=str,
        default=None,
        help="Path to event_store JSONL file (default: state/workflow_executions.jsonl)",
    )
    parser.add_argument(
        "--phase",
        type=str,
        default=None,
        choices=list(PHASE_CRITERIA.keys()),
        help="Validate single phase (default: all phases)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON report to file (default: stdout)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print human-readable summary to stdout (default: JSON)",
    )
    parser.add_argument(
        "--check-event-count",
        action="store_true",
        help="Only report event counts per phase, no validation",
    )

    args = parser.parse_args()

    # ── event count check (lightweight) ──────────────────────────────────────
    if args.check_event_count:
        reader = EventStoreReader(args.event_store)
        print("\nEvent counts per phase:")
        print("-" * 60)
        for phase in PHASE_CRITERIA.keys():
            events = reader.read_shadow_events(phase)
            status = "✓" if len(events) >= PHASE_CRITERIA[phase].min_cycles else "⚠"
            print(f"{status} {phase:25} {len(events):4d} events (min: {PHASE_CRITERIA[phase].min_cycles})")
        return

    # ── run validation ──────────────────────────────────────────────────────
    _log.info("Running phase validation...")
    report = validate_all_phases(args.event_store)

    # ── output format ───────────────────────────────────────────────────────
    if args.summary:
        print("\n" + report.summary_text())
    else:
        report_json = report.to_dict()

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as fh:
            json.dump(report_json, fh, indent=2)
        _log.info(f"Report written to {output_path}")
    else:
        print(json.dumps(report_json, indent=2))

    # ── exit code ────────────────────────────────────────────────────────────
    sys.exit(0 if report.phases_passed == report.total_phases else 1)


if __name__ == "__main__":
    main()
