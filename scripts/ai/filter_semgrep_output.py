"""Reduce Semgrep JSON or text output to actionable findings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def filter_json(payload: dict) -> dict:
    results = payload.get("results", [])
    return {
        "errors": payload.get("errors", []),
        "results": [
            {key: item.get(key) for key in ("check_id", "path", "start", "extra")}
            for item in results
            if str(item.get("extra", {}).get("severity", "")).upper() in {"ERROR", "WARNING"}
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    text = args.input.read_text(encoding="utf-8", errors="replace")
    try:
        print(json.dumps(filter_json(json.loads(text)), indent=2))
    except json.JSONDecodeError:
        print("\n".join(line for line in text.splitlines() if any(token in line.upper() for token in ("WARNING", "ERROR", "CRITICAL"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
