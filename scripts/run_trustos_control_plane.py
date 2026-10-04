"""Run the offline TrustOS Control Plane report."""
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

from evaluation.trustos.control_plane import ACTION_CATEGORIES, build_policy_packs_from_controls, build_trust_controls
from evaluation.trustos.gate_runner import evaluate_action
from evaluation.trustos.trustos_report import build_trustos_combined_report

SECRET_KEYS = {"actual_secret_value", "api_key", "raw_api_key", "raw_oauth_token", "oauth_token", "access_token", "refresh_token", "password", "private_key", "private_key_material", "authorization", "cookie", "cookies", "raw_payload", "raw_html", "html", "body", "response_body", "prompt", "source_code", "internal_prompt", "other_client_data", "client_private_data", "cross_client_data"}


def _path(value: str, *, must_exist: bool = True, allow_external: bool = False) -> Path:
    raw = Path(value)
    normalized = str(value).replace("\\", "/")
    if any(part == ".." for part in raw.parts) or any(part == ".." for part in Path(normalized).parts):
        raise ValueError("path traversal is not accepted")
    path = (raw if raw.is_absolute() else ROOT / raw).resolve()
    if not allow_external and not path.is_relative_to(ROOT):
        raise ValueError("path must remain inside the repository")
    if must_exist and not path.is_file():
        raise FileNotFoundError(str(path))
    return path


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


def _load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    payload = json.loads(_path(value).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or _secret_like(payload):
        raise ValueError("secret-like or malformed TrustOS input is not accepted")
    return payload


def _filtered_report(report: Any, policy_pack: str | None, client_safe: bool) -> dict[str, Any]:
    data = report.to_dict(client_safe=client_safe)
    if policy_pack:
        data["policy_packs"] = [item for item in data.get("policy_packs", []) if item.get("pack_id") == policy_pack]
        if "controls" in data:
            allowed = {item["control_id"] for item in data["policy_packs"] for item in item.get("controls", [])}
            data["controls"] = [item for item in data["controls"] if item.get("control_id") in allowed]
    return data


def _write(output_value: str, report: Any, policy_pack: str | None, client_safe: bool) -> None:
    output = _path(output_value, must_exist=False, allow_external=True)
    output.mkdir(parents=True, exist_ok=True)
    data = _filtered_report(report, policy_pack, client_safe)
    files = {
        "trustos_report.json": json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "trustos_report.md": report.to_markdown(client_safe=client_safe),
        "control_registry.json": json.dumps(data.get("controls", []), indent=2, sort_keys=True) + "\n",
        "policy_packs.json": json.dumps(data.get("policy_packs", []), indent=2, sort_keys=True) + "\n",
        "evidence_locker.json": json.dumps(data.get("evidence_records", []), indent=2, sort_keys=True) + "\n",
        "gate_results.json": json.dumps(data.get("gate_results", []), indent=2, sort_keys=True) + "\n",
        "public_launch_readiness.json": json.dumps(data.get("public_launch_readiness", {}), indent=2, sort_keys=True) + "\n",
        "client_trustops_report.md": report.client_trustos_report.to_markdown(client_safe=True),
        "lawyer_ready_packet.md": "# Lawyer-ready Packet\n\n" + "\n".join(f"- {item}" for item in report.client_trustos_report.lawyer_packet.requested_review) + "\n\nNo legal conclusion is provided.\n",
        "accountant_ready_packet.md": "# Accountant-ready Packet\n\n" + "\n".join(f"- {item}" for item in report.client_trustos_report.accountant_packet.requested_review) + "\n\nNo tax advice or filing is provided.\n",
        "security_reviewer_packet.md": "# Security Reviewer Packet\n\n" + "\n".join(f"- {item}" for item in report.client_trustos_report.security_packet.requested_review) + "\n\nNo scanner was run.\n",
        "service_opportunities.json": json.dumps(data.get("service_package_opportunities", []), indent=2) + "\n",
    }
    for name, content in files.items():
        (output / name).write_text(content, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=ACTION_CATEGORIES)
    parser.add_argument("--policy-pack", choices=("security_baseline", "ai_agent_security", "provider_activation", "privacy_legal_baseline", "tax_accounting_readiness", "public_launch_readiness", "client_trustos_service"))
    parser.add_argument("--context")
    parser.add_argument("--client-safe", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    if args.json and args.markdown:
        parser.error("choose --json or --markdown")
    try:
        context = _load(args.context)
        if args.action:
            context = dict(context)
            context["_requested_action"] = args.action
        report = build_trustos_combined_report(context=context, client_safe=args.client_safe)
        if args.action:
            result = evaluate_action(args.action, context=context)
            data = _filtered_report(report, args.policy_pack, args.client_safe)
            data["requested_action_result"] = result.to_dict()
        else:
            data = _filtered_report(report, args.policy_pack, args.client_safe)
        if args.output:
            _write(args.output, report, args.policy_pack, args.client_safe)
        print(report.to_markdown(client_safe=args.client_safe) if args.markdown else json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"trustos_error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
