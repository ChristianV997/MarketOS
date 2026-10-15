"""Run the TikTok commercial-attention capability contract (blocked by default).

Ordinary runs report commercial ineligibility / no supported source with zero
evidence rows. Offline fixture/fake demos require ``--allow-offline-demo`` and
are never operational live capability.
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

from evaluation.commerce.tiktok_research_evidence import (  # noqa: E402
    FakeTikTokResearchTransport,
    build_tiktok_research_evidence,
    render_markdown,
)

DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "tiktok_research_evidence" / "sanitized_creative_snapshot.json"
MODES = (
    "blocked_ineligible_commercial_use",
    "blocked_no_supported_commercial_attention_source",
    "not_configured",
    "fixture_demo",
    "manual_import",
    "fake_transport",
)
OFFLINE_DEMO_MODES = {"fixture_demo", "manual_import", "fake_transport"}


def _path(value: str, *, must_exist: bool = True) -> Path:
    raw = Path(value)
    if ".." in raw.parts:
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("path must remain inside the repository")
    if must_exist and not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _write(output_value: str, report: Any) -> None:
    output = Path(output_value)
    if ".." in output.parts:
        raise ValueError("path traversal is not accepted")
    resolved = (output if output.is_absolute() else ROOT / output).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    (resolved / "tiktok_research_evidence_report.json").write_text(
        json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (resolved / "tiktok_research_evidence_report.md").write_text(render_markdown(report), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=MODES, default="blocked_ineligible_commercial_use")
    parser.add_argument("--fixture")
    parser.add_argument(
        "--allow-offline-demo",
        action="store_true",
        help="Required for fixture_demo/manual_import/fake_transport; not an operational capability",
    )
    parser.add_argument("--allow-live", action="store_true", help="Always blocked; documents fail-closed live request")
    parser.add_argument("--fake-error", action="store_true", help="With fake_transport, return a non-success fake response")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        transport = None
        fixture = None
        rows = None
        mode = args.mode
        if mode in OFFLINE_DEMO_MODES and not args.allow_offline_demo and not args.allow_live:
            # Still call builder so the precise blocked_offline_demo_disabled status is produced.
            pass
        if mode == "fake_transport" and args.allow_offline_demo:
            sample = [
                {
                    "candidate_id": "mini-thermal-printer",
                    "query": "mini thermal printer",
                    "platform": "tiktok",
                    "source_type": "tiktok_creative_center_snapshot",
                    "hook": "Print labels from a phone",
                    "view_count": "12000",
                    "like_count": "800",
                    "geography": "US",
                    "language": "en",
                    "observed_at": "2026-09-01T12:00:00Z",
                }
            ]
            transport = FakeTikTokResearchTransport(
                status="error" if args.fake_error else "ok",
                rows=() if args.fake_error else tuple(sample),
            )
        elif mode in {"fixture_demo", "manual_import"} and args.allow_offline_demo:
            fixture = _path(args.fixture) if args.fixture else (DEFAULT_FIXTURE if DEFAULT_FIXTURE.is_file() else None)
            if fixture is None:
                raise FileNotFoundError("fixture path required for fixture_demo/manual_import")
        report = build_tiktok_research_evidence(
            mode=mode,
            fixture_path=fixture,
            rows=rows,
            transport=transport,
            allow_live=bool(args.allow_live),
            allow_offline_demo=bool(args.allow_offline_demo),
        )
        if args.output:
            _write(args.output, report)
        if args.markdown:
            print(render_markdown(report))
        else:
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"tiktok_research_evidence_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
