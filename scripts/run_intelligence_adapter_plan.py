"""Render the offline Intelligence Live Read-Only Adapter Plan."""
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

from evaluation.commerce.intelligence_adapter_plan import build_intelligence_adapter_plan

SECRET_KEYS = {"actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token", "access_token", "refresh_token", "password", "private_key", "private_key_material", "authorization", "cookie", "raw_payload", "raw_html", "html", "body", "response_body", "javascript"}


def _safe_path(value: str | None, *, must_exist: bool = True) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    # Reject both native and cross-platform traversal spellings before
    # resolving. CI runs on POSIX while operators commonly pass Windows paths.
    raw_text = str(value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(raw_text).parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if must_exist and not path.is_file():
        raise FileNotFoundError(str(path))
    return path


# "sk-" is a credential prefix only when it starts a token; it is also the tail of words such as
# desk-clamp-lamp or risk-review-pack, so it must not follow a letter or digit. A URL-escape (%3d) or a
# literal backslash escape (\\n) before it still counts as a boundary.
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower().replace("-", "_") in SECRET_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "-----begin " in lowered or "bearer " in lowered or _SK_PREFIX.search(lowered) is not None or any(marker in lowered for marker in ("ghp_", "xoxb-", "AIza"))
    return False


def _load_fixture_dir(value: str | None) -> dict[str, dict[str, Any]]:
    directory = _safe_path(value, must_exist=False)
    if directory is None:
        return {}
    if not directory.is_dir():
        raise ValueError("fixture directory must be a directory")
    mapping = {
        "apify": "apify_marketplace_snapshot_dry_run.json",
        "dataforseo": "dataforseo_serp_snapshot_dry_run.json",
        "serpapi": "serpapi_shopping_snapshot_dry_run.json",
        "manual-import": "manual_import_marketplace_snapshot.json",
    }
    result: dict[str, dict[str, Any]] = {}
    for provider, name in mapping.items():
        path = directory / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or _secret_like(payload):
                raise ValueError(f"secret-like or malformed fixture: {name}")
            result[provider] = payload
    return result


def _write_outputs(value: str, report: Any) -> None:
    output = _safe_path(value, must_exist=False)
    assert output is not None
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "intelligence_adapter_plan_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "intelligence_adapter_plan_report.md": report.to_markdown(),
        "provider_adapter_contracts.json": json.dumps(data["contracts"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "provider_request_plans.json": json.dumps(data["request_plans"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "approval_credential_checks.json": json.dumps(data["readiness_by_provider"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "provider_cost_plan.json": json.dumps(data["cost_plan"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "evidence_mappings.json": json.dumps(data["evidence_mappings"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "normalization_rules.json": json.dumps(data["normalization_summary"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "dry_run_results.json": json.dumps(data["dry_run_results"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "blocked_providers.json": json.dumps(data["providers_blocked"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider")
    parser.add_argument("--data-need")
    parser.add_argument("--fixture-dir")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        report = build_intelligence_adapter_plan(provider=args.provider, data_need=args.data_need, fixture_payloads=_load_fixture_dir(args.fixture_dir))
        if args.output:
            _write_outputs(args.output, report)
        print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"intelligence_adapter_plan_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
