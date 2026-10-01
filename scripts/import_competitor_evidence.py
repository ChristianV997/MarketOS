"""Import an operator competitor CSV as manual evidence. Never fetches a listing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.adapters.research.competition_evidence import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    import_manual_competitor_csv,
)
from backend.discovery.csv_ingestion import MAX_ROWS  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a local competitor CSV as manual evidence. No network calls.")
    parser.add_argument("--csv", required=True, dest="csv_path")
    parser.add_argument("--candidate-id", required=True)
    args = parser.parse_args(argv)
    source = Path(args.csv_path)
    try:
        size = source.stat().st_size
    except OSError:
        report = {"status": "rejected", "rejections": [{"code": "file_unavailable"}], "evidence_class": "manual", "network_calls": False}
        print(json.dumps(report, sort_keys=True))
        return 1
    if size > MAX_RESPONSE_BYTES:
        report = import_manual_competitor_csv("", candidate_id=args.candidate_id)
        report = {"status": "rejected", "candidate_id": report["candidate_id"], "rejections": [{"code": "file_too_large"}], "evidence_class": "manual", "evidence_state": "manual_import", "live_validated": False, "network_calls": False, "provider_calls": False}
        print(json.dumps(report, sort_keys=True))
        return 1
    try:
        text = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        report = {"status": "rejected", "rejections": [{"code": "undecodable"}], "evidence_class": "manual", "network_calls": False}
        print(json.dumps(report, sort_keys=True))
        return 1
    report = import_manual_competitor_csv(text, candidate_id=args.candidate_id, max_bytes=MAX_RESPONSE_BYTES, max_rows=MAX_ROWS)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "accepted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
