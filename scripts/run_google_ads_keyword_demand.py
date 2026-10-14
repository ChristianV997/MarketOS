"""Produce a read-only Google Ads keyword-demand report.

The operational path never reads credentials, never opens a Google Ads socket,
and has no fixture or manual keyword fallback. A report with zero observations
is the expected result until a later transport exists behind the same gates.
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

from evaluation.commerce.google_ads_keyword_demand_adapter import (  # noqa: E402
    GoogleAdsKeywordDemandError,
    KeywordDemandAuthorization,
    collect_google_ads_keyword_demand,
)


def _path(value: str, *, must_exist: bool) -> Path:
    raw = Path(value)
    text = str(value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(text).parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not raw.is_absolute() and not path.is_relative_to(ROOT):
        raise ValueError("path must remain inside the repository")
    if path.suffix.lower() != ".json":
        raise ValueError("path must be a json file")
    if must_exist and not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _authorization(payload: dict[str, Any]) -> KeywordDemandAuthorization:
    raw = payload.get("authorization") or {}
    if not isinstance(raw, dict):
        raise ValueError("authorization must be an object")
    allowed = {
        "approval_status",
        "credential_reference_present",
        "cloud_project_access_level",
        "terms_review_complete",
        "privacy_review_complete",
        "quota_limit_acknowledged",
        "cost_unknown_acknowledged",
    }
    if any(key not in allowed for key in raw):
        raise ValueError("authorization contains an unsupported field")
    level = raw.get("cloud_project_access_level")
    return KeywordDemandAuthorization(
        approval_status=str(raw.get("approval_status") or "missing"),
        credential_reference_present=raw.get("credential_reference_present") is True,
        cloud_project_access_level=None if level in (None, "") else str(level),
        terms_review_complete=raw.get("terms_review_complete") is True,
        privacy_review_complete=raw.get("privacy_review_complete") is True,
        quota_limit_acknowledged=raw.get("quota_limit_acknowledged") is True,
        cost_unknown_acknowledged=raw.get("cost_unknown_acknowledged") is True,
    )


def _load(value: str) -> tuple[dict[str, Any], KeywordDemandAuthorization, dict[str, str] | None]:
    path = _path(value, must_exist=True)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("request must be a JSON object")
    links = payload.get("identity_links")
    if links is not None and not isinstance(links, dict):
        raise ValueError("identity_links must be an object")
    request = {
        key: item
        for key, item in payload.items()
        if key not in {"authorization", "identity_links"}
    }
    identity = None if links is None else {str(key): str(item) for key, item in links.items()}
    return request, _authorization(payload), identity


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, help="metadata-only JSON request; no secrets")
    parser.add_argument("--output", help="optional JSON report path")
    args = parser.parse_args(argv)
    try:
        request, authorization, identity_links = _load(args.request)
        report = collect_google_ads_keyword_demand(
            request,
            authorization,
            identity_links=identity_links,
        )
        body = json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if args.output:
            output = _path(args.output, must_exist=False)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(body, encoding="utf-8")
        sys.stdout.write(body)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, GoogleAdsKeywordDemandError):
        print("google_ads_keyword_demand_error: request was not accepted", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
