"""Print one draft-only creative experiment brief. No campaign and no export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.commerce.creative_experiment_brief import build_creative_experiment_brief  # noqa: E402


def _read(value: str, *, label: str) -> dict[str, Any]:
    normalized = value.replace("\\", "/")
    target = Path(value)
    if ".." in target.parts or ".." in normalized.split("/") or target.suffix.lower() != ".json":
        raise ValueError("malformed creative brief input")
    if not target.is_file():
        raise ValueError("malformed creative brief input")
    try:
        parsed = json.loads(target.read_text(encoding="utf8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("malformed creative brief input") from exc
    if not isinstance(parsed, dict):
        raise ValueError("malformed creative brief input")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft a creative experiment brief without launching anything")
    parser.add_argument("--synthesis", required=True)
    parser.add_argument("--attention", required=True)
    parser.add_argument("--geography", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--asserted-claim", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        synthesis = _read(args.synthesis, label="synthesis")
        attention = _read(args.attention, label="attention")
        document = build_creative_experiment_brief(
            synthesis=synthesis,
            consumer_attention=attention,
            target_geography=args.geography,
            target_language=args.language,
            asserted_claims=args.asserted_claim,
        )
    except ValueError:
        print(json.dumps({"error": "malformed creative brief input"}, sort_keys=True))
        return 2
    print(json.dumps(document, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
