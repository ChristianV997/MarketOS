"""Compose a local Google Trends fixture into consumer-attention trace evidence.

Offline only. Does not call Google, load credentials, or write a file.
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

from evaluation.commerce.google_trends_attention_bridge import compose_google_trends_attention
from evaluation.secret_markers import contains_boundary_prefixed_sk_token

SECRET_KEYS = {
    "actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token",
    "access_token", "refresh_token", "password", "private_key", "private_key_material",
    "authorization", "cookie", "cookies", "raw_payload", "raw_html", "html", "body",
    "response_body", "javascript", "browser_trace",
}


def _path(value: str) -> Path:
    raw = Path(value)
    text = str(value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(text).parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("path must remain inside the repository")
    if not path.is_file():
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


def _links(values: list[str] | None) -> dict[str, str]:
    links: dict[str, str] = {}
    for item in values or []:
        term, separator, candidate = item.partition("=")
        if not separator or not term.strip() or not candidate.strip():
            raise ValueError("identity link must be term=candidate_id")
        links[term.strip()] = candidate.strip()
    return links


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", help="Repository-local fixture JSON. Omit for the adapter's built-in synthetic fixture.")
    parser.add_argument("--identity-link", action="append", default=[], help="Exact term=candidate_id. Not a hint or fuzzy match.")
    parser.add_argument("--as-of")
    parser.add_argument("--live-read-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        links = _links(args.identity_link)
        if args.fixture:
            payload = json.loads(_path(args.fixture).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or _secret_like(payload):
                raise ValueError("secret-like or malformed fixture input is not accepted")
            composition = compose_google_trends_attention(
                payload,
                identity_links=links,
                as_of=args.as_of,
                live_read_only=args.live_read_only,
            )
        else:
            from evaluation.commerce.google_trends_interest_adapter import build_google_trends_interest_report

            composition = compose_google_trends_attention(
                build_google_trends_interest_report(live_read_only=args.live_read_only),
                identity_links=links,
                as_of=args.as_of,
            )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(composition.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
