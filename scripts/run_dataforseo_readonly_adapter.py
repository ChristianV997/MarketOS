"""Run the offline DataForSEO read-only adapter harness."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.commerce.dataforseo_adapter import REQUEST_KINDS, build_dataforseo_adapter_report

SECRET_KEYS = {"actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token", "access_token", "refresh_token", "password", "private_key", "private_key_material", "authorization", "cookie", "cookies", "raw_payload", "raw_html", "html", "body", "response_body", "javascript", "browser_trace"}
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")


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
        return any(str(key).lower().replace("-", "_") in SECRET_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "-----begin " in lowered or "bearer " in lowered or _SK_PREFIX.search(lowered) is not None or any(marker in lowered for marker in ("ghp_", "xoxb-", "aiza"))
    return False


def _load(value: str | None) -> tuple[dict[str, Any] | None, str]:
    if not value:
        return None, "fixture://dataforseo-default"
    path = _path(value)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or _secret_like(payload):
        raise ValueError("secret-like or malformed fixture input is not accepted")
    return payload, str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else "fixture://external-sanitized"


def _write(output_value: str, report: Any) -> None:
    output = _path(output_value, must_exist=False, allow_external=True)
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "dataforseo_adapter_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "dataforseo_adapter_report.md": report.to_markdown(),
        "dataforseo_request_plan.json": json.dumps(data["request_plan"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "dataforseo_readiness_checks.json": json.dumps({"approval": data["approval_readiness"], "credential": data["credential_readiness"], "terms_privacy": data["terms_privacy_status"]}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "dataforseo_cost_plan.json": json.dumps({"cost": data["cost_estimate"], "rate": data["rate_limit_plan"]}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "dataforseo_normalized_signals.json": json.dumps({"search": data["parse_result"]["search_signals"], "shopping": data["parse_result"]["shopping_signals"], "competitors": data["parse_result"]["competitor_signals"]}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "dataforseo_opportunity_context.json": json.dumps({"search_context": data["opportunity_search_context"], "product_validation_summary": data["product_validation_search_summary"]}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "blocked_live_activation.json": json.dumps(data["blocked_live_activation"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture")
    parser.add_argument("--request-kind", choices=REQUEST_KINDS, default="serp_google_organic_snapshot")
    parser.add_argument("--keyword", action="append", default=[])
    parser.add_argument("--feed-opportunity-context", action="store_true")
    parser.add_argument("--live-read-only", action="store_true")
    parser.add_argument("--max-keywords", type=int, default=10)
    parser.add_argument("--max-requests", type=int, default=10)
    parser.add_argument("--max-items", type=int, default=100)
    parser.add_argument("--max-cost", type=float, default=2.0)
    parser.add_argument("--monthly-budget-cap", type=float, default=50.0)
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        payload, source_file = _load(args.fixture)
        report = build_dataforseo_adapter_report(generated_at="offline-deterministic", request_kind=args.request_kind, keywords=tuple(args.keyword), payload=payload, source_file=source_file, live_read_only=args.live_read_only, max_keywords=args.max_keywords, max_requests=args.max_requests, max_items=args.max_items, max_cost=args.max_cost, monthly_budget_cap=args.monthly_budget_cap)
        if args.output:
            _write(args.output, report)
        print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"dataforseo_adapter_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
