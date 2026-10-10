"""Run the offline SerpApi commerce-projection harness.

Thin CLI over evaluation.commerce.serpapi_commerce_projection -- itself a
thin downstream consumer of the existing SerpApi runtime adapter
(backend.adapters.research.serpapi). No SerpApi call, no credential, no
network occurs anywhere in this script.
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

from evaluation.commerce.serpapi_commerce_projection import build_serpapi_commerce_projection
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
        return "-----begin " in lowered or "bearer " in lowered or contains_boundary_prefixed_sk_token(value) or any(marker in lowered for marker in ("ghp_", "xoxb-", "aiza"))
    return False


def _load_fixture(value: str | None) -> dict[str, Any] | None:
    if not value:
        return None
    path = _path(value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or _secret_like(payload):
        raise ValueError("secret-like or malformed fixture input is not accepted")
    return payload


def _write(output_value: str, report: Any) -> None:
    output = _path(output_value, must_exist=False, allow_external=True)
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "serpapi_commerce_projection_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "serpapi_commerce_projection_report.md": report.to_markdown(),
        "serpapi_commerce_projection_records.json": json.dumps(data["records"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="portable espresso maker")
    parser.add_argument("--fixture")
    parser.add_argument("--marketplace", default=None, help="explicit marketplace name; never inferred")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        payload = _load_fixture(args.fixture)
        report = build_serpapi_commerce_projection(
            query=args.query, fixture_payload=payload, marketplace=args.marketplace,
            generated_at="offline-deterministic",
        )
        if args.output:
            _write(args.output, report)
        print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"serpapi_commerce_projection_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
