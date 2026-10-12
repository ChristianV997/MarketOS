"""Run the offline Google Trends organic search-interest adapter harness."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.google_trends_interest_adapter import (
    REQUEST_KINDS,
    TIME_RESOLUTIONS,
    GoogleTrendsInterestAdapterError,
    build_google_trends_interest_report,
)
from evaluation.secret_markers import contains_boundary_prefixed_sk_token

SECRET_KEYS = {
    "actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token",
    "access_token", "refresh_token", "password", "private_key", "private_key_material",
    "authorization", "cookie", "cookies", "raw_payload", "raw_html", "html", "body",
    "response_body", "javascript", "browser_trace",
}


def _path(value: str, *, must_exist: bool = True, allow_external: bool = False) -> Path:
    raw = Path(value)
    text = str(value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(text).parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not allow_external and not path.is_relative_to(ROOT):
        raise ValueError("path must remain inside the repository")
    if must_exist and not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).lower().replace("-", "_") in SECRET_KEYS
            or _secret_like(str(key))
            or _secret_like(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return (
            "-----begin " in lowered
            or "bearer " in lowered
            or contains_boundary_prefixed_sk_token(value)
            or any(marker in lowered for marker in ("ghp_", "xoxb-", "aiza"))
        )
    return False


def _load(value: str | None) -> tuple[dict[str, Any] | None, str]:
    if not value:
        return None, "fixture://google-trends-interest-default"
    path = _path(value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or _secret_like(payload):
        raise ValueError("secret-like or malformed fixture input is not accepted")
    return payload, str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else "fixture://external-sanitized"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture")
    parser.add_argument("--request-kind", choices=REQUEST_KINDS, default="interest_over_time")
    parser.add_argument("--term", action="append", dest="terms")
    parser.add_argument("--geography", default="US")
    parser.add_argument("--language", default="en")
    parser.add_argument("--time-resolution", choices=TIME_RESOLUTIONS, default="WEEK")
    parser.add_argument("--window-start", default="2024-01-01")
    parser.add_argument("--window-end", default="2024-03-31")
    parser.add_argument("--transport-scenario", default=None)
    parser.add_argument("--live-read-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload, source = _load(args.fixture)
        report = build_google_trends_interest_report(
            request_kind=args.request_kind,
            terms=args.terms or ("desk fan",),
            geography=args.geography,
            language=args.language,
            time_resolution=args.time_resolution,
            window_start=args.window_start,
            window_end=args.window_end,
            payload=payload,
            source_file=source,
            live_read_only=args.live_read_only,
            transport_scenario=args.transport_scenario,
        )
    except (OSError, ValueError, GoogleTrendsInterestAdapterError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.markdown and not args.json:
        print(report.to_markdown())
        return 0
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
