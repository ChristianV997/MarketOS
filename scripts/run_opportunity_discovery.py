#!/usr/bin/env python3
"""Run the offline opportunity-discovery adapter over a bounded JSON input."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.opportunity_discovery import (  # noqa: E402
    DISCOVERY_MODES,
    OpportunityDiscoveryError,
    load_payload,
    render_markdown,
    run_discovery,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=DISCOVERY_MODES, required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        report = run_discovery(args.mode, load_payload(raw))
    except (OSError, OpportunityDiscoveryError) as exc:
        print(json.dumps({"status": "malformed", "error": getattr(exc, "code", "input_unavailable")}, sort_keys=True), file=sys.stderr)
        return 2
    if args.format == "markdown":
        print(render_markdown(report))
    else:
        print(json.dumps(report.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
