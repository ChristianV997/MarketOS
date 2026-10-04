"""Generate the offline CompanyOS provider, credential, and subscription registry."""
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

from evaluation.companyos.provider_credential_report import build_provider_credential_report

SECRET_KEYS = {"actual_secret_value", "raw_api_key", "raw_oauth_token", "password", "private_key_material", "api_key", "access_token", "refresh_token", "client_secret"}


def _path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    if any(part == ".." for part in raw.parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _output(value: str) -> Path:
    raw = Path(value)
    if any(part == ".." for part in raw.parts):
        raise ValueError("output traversal is not accepted")
    return (raw if raw.is_absolute() else ROOT / raw).resolve()


# "sk-" is a credential prefix only when it starts a token; it is also the tail of words such as
# desk-clamp-lamp or risk-review-pack, so it must not follow a letter or digit.
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-")


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        return any(str(key).lower().replace("-", "_") in SECRET_KEYS or _secret_like(item) for key, item in value.items())
    if isinstance(value, list):
        return any(_secret_like(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        return "-----begin " in lowered or "bearer " in lowered or _SK_PREFIX.search(lowered) is not None or any(marker in lowered for marker in ("ghp_", "xoxb-", "AIza"))
    return False


def _load(value: str | None) -> dict[str, Any] | None:
    path = _path(value)
    if path is None:
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    if _secret_like(data):
        raise ValueError(f"secret-like fields are not accepted in {path.name}")
    return data


def _export(path_value: str, report: Any) -> None:
    output = _output(path_value)
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    files = {
        "provider_credential_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "provider_credential_report.md": report.to_markdown(),
        "credential_registry.json": json.dumps(data["credentials"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "provider_registry.json": json.dumps(data["providers"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "subscription_registry.json": json.dumps(data["subscriptions"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "intelligence_provider_plan.json": json.dumps(data["intelligence_plan"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "provider_capability_matrix.json": json.dumps(data["providers"]["capability_matrix"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "subscription_cost_plan.json": json.dumps(data["subscriptions"]["cost_estimates"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "credential_gap_report.json": json.dumps(data["credential_gaps"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "activation_gates.json": json.dumps(data["activation_gates"], indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-credentials", action="store_true")
    parser.add_argument("--include-providers", action="store_true")
    parser.add_argument("--include-subscriptions", action="store_true")
    parser.add_argument("--include-intelligence-plan", action="store_true")
    parser.add_argument("--phase")
    parser.add_argument("--provider")
    parser.add_argument("--provider-seed")
    parser.add_argument("--credential-seed")
    parser.add_argument("--subscription-seed")
    parser.add_argument("--intelligence-plan-seed")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        seeds = {"providers": _load(args.provider_seed), "credentials": _load(args.credential_seed), "subscriptions": _load(args.subscription_seed), "intelligence_plan": _load(args.intelligence_plan_seed)}
        seeds = {key: value for key, value in seeds.items() if value is not None}
        report = build_provider_credential_report(phase=args.phase, provider=args.provider, seeds=seeds)
        if args.output:
            _export(args.output, report)
        print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"companyos_provider_registry_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
