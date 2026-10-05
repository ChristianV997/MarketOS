"""Generate the offline CompanyOS Approval Ledger and action simulations."""
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

from evaluation.companyos.approval_ledger import build_approval_ledger, simulate_action

SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "private_key", "access_token", "refresh_token", "client_secret", "authorization", "cookie"}
_SK_PREFIX = re.compile(r"(?<![a-z0-9])sk-|(?<=%[0-9a-f]{2})sk-|(?<=\\[nrt])sk-")


def _path(value: str | None) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    if any(part == ".." for part in raw.parts):
        raise ValueError("path traversal is not accepted")
    path = raw if raw.is_absolute() else ROOT / raw
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _output_path(value: str) -> Path:
    raw = Path(value)
    if any(part == ".." for part in raw.parts):
        raise ValueError("output traversal is not accepted")
    path = raw if raw.is_absolute() else ROOT / raw
    return path.resolve()


def _secret_like(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in SECRET_KEYS:
                return True
            if _secret_like(item):
                return True
    elif isinstance(value, list):
        return any(_secret_like(item) for item in value)
    elif isinstance(value, str):
        lowered = value.lower()
        return _SK_PREFIX.search(lowered) is not None or any(marker in lowered for marker in ("bearer ", "-----begin ", "ghp_"))
    return False


def _load(path_value: str | None) -> Any:
    path = _path(path_value)
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if _secret_like(value):
        raise ValueError(f"secret-like fields are not accepted in {path.name}")
    return value


def _export(output_value: str, report: Any) -> None:
    output = _output_path(output_value)
    output.mkdir(parents=True, exist_ok=True)
    data = report.to_dict()
    simulations = data.get("simulations", [])
    files = {
        "approval_ledger_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "approval_ledger_report.md": report.to_markdown(),
        "approval_queue.json": json.dumps(data["queue_summary"], indent=2, sort_keys=True) + "\n",
        "approval_policies.json": json.dumps(data["policies"], indent=2, sort_keys=True) + "\n",
        "approval_audit_trail.json": json.dumps(data["audit_events"], indent=2, sort_keys=True) + "\n",
        "approval_simulations.json": json.dumps(simulations, indent=2, sort_keys=True) + "\n",
        "blocked_actions.json": json.dumps([item for item in data["requests"] if item["status"] == "blocked_by_policy"], indent=2, sort_keys=True) + "\n",
        "budget_caps.json": json.dumps([item["budget_cap"] for item in data["policies"]], indent=2, sort_keys=True) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry-report")
    parser.add_argument("--approval-requests")
    parser.add_argument("--simulate-action")
    parser.add_argument("--requested-budget", type=float, default=0.0)
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        registry = _load(args.registry_report)
        requests = _load(args.approval_requests)
        if requests is not None and not isinstance(requests, list):
            raise ValueError("approval request input must be a JSON array")
        simulations = ()
        if args.simulate_action:
            simulations = (simulate_action(args.simulate_action, requested_budget=args.requested_budget),)
        report = build_approval_ledger(registry_report=registry, approval_requests=requests, simulations=simulations)
        if args.output:
            _export(args.output, report)
        print(report.to_markdown() if args.markdown else json.dumps(report.to_dict(), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"companyos_approval_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
