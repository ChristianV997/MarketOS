"""Read-only parity report for the default-off shadow-mode event migration pilot."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.events.migration_compatibility import build_dual_write_compatibility_report
from backend.events.replay_certification import load_canonical_jsonl

FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "event_migration_pilot"


def _read_legacy(path: Path) -> list[dict]:
    records: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{number}: invalid legacy JSON") from exc
    return records


def _markdown(report: dict) -> str:
    mismatches = ", ".join(report["mismatches"]) or "none"
    hashes = "\n".join(f"- `{value}`" for value in report["replay_hashes"]) or "- none"
    return "\n".join([
        "# Event Migration Pilot Report", "",
        "The legacy journal remains authoritative. The canonical event is a dry-run, non-authoritative mirror.", "",
        f"- Pilot: `{report['pilot_name']}`",
        f"- Legacy events: {report['legacy_count']}",
        f"- Canonical events: {report['canonical_count']}",
        f"- Parity: **{report['parity']}**",
        f"- Mismatches: {mismatches}",
        f"- Legacy fields preserved: {report['legacy_fields_preserved']}",
        f"- Canonical non-authoritative: {report['canonical_non_authoritative']}",
        f"- Ordering preserved: {report['ordering_preserved']}",
        "", "## Replay hashes", "", hashes, "",
        "## Recommendation", "", f"- {report['recommendation']}", "",
        "No feature flag, provider, live action, or external state was changed.", "",
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--legacy-path")
    parser.add_argument("--canonical-path")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true")
    mode.add_argument("--markdown", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    legacy_path = Path(args.legacy_path) if args.legacy_path else FIXTURE_ROOT / "legacy_only_input.jsonl"
    canonical_path = Path(args.canonical_path) if args.canonical_path else FIXTURE_ROOT / "canonical_expected.jsonl"
    if not legacy_path.is_file() or not canonical_path.is_file():
        print("legacy and canonical input files must exist", file=sys.stderr)
        return 2
    try:
        report = build_dual_write_compatibility_report(_read_legacy(legacy_path), load_canonical_jsonl(canonical_path)).to_dict()
    except Exception as exc:
        print(f"pilot report failed: {exc}", file=sys.stderr)
        return 1
    content = _markdown(report) if args.markdown else json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
