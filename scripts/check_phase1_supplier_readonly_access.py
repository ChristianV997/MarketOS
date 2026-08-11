"""Preflight the explicitly gated Phase 1 authenticated supplier read path.

This command performs no network call unless both ``--allow-network`` and the
server-side CJ read-only gate/credentials are present. It never prints secret
values and returns a structured status suitable for deployment checks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.adapters.research.cj_readonly_api import CjReadOnlySupplierAdapter, explain_cj_read_only_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check gated, read-only supplier evidence readiness.")
    parser.add_argument("--provider", default="cj")
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--query", default="portable espresso maker")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)
    readiness = explain_cj_read_only_readiness(allow_network=args.allow_network)
    readiness["provider_requested"] = args.provider
    if args.provider != "cj":
        readiness["status"] = "provider_mismatch"
        readiness["configured"] = False
    probe = {"attempted": False, "status": readiness["status"], "observed_product_count": 0, "warnings": []}
    if args.provider == "cj" and args.allow_network and readiness["status"] == "ready":
        result = CjReadOnlySupplierAdapter().search(args.query, limit=max(1, min(args.limit, 3)), allow_network=True)
        probe = {
            "attempted": result.attempted, "status": result.status,
            "observed_product_count": len(result.products), "warnings": list(result.warnings),
            "endpoint_statuses": result.endpoint_statuses,
        }
    report = {
        "status": probe["status"], "readiness": readiness, "probe": probe,
        "read_only": True, "mutated": False, "credentials_exposed": False,
        "forbidden_actions": readiness.get("forbidden_actions", []),
        "next_action": (
            "Provide CJ_EMAIL/CJ_API_KEY through server environment and set MARKETOS_SUPPLIER_AUTH_READONLY=1 before an explicitly approved probe."
            if probe["status"] == "credential_missing" else
            "Set MARKETOS_SUPPLIER_AUTH_READONLY=1 on the server; no network was attempted."
            if probe["status"] == "live_flag_disabled" else
            "Use --allow-network only for an operator-approved read-only probe."
            if probe["status"] == "network_gate_required" else
            "Review the structured provider result; no mutation endpoints are available to this adapter."
        ),
    }
    if args.markdown:
        print("# Phase 1 supplier read-only preflight\n\n" +
              f"- Status: `{report['status']}`\n- Provider: `cj`\n- Credentials present: `{readiness['credentials_present_redacted']}`\n"+
              f"- Live flag enabled: `{readiness['live_flag_enabled']}`\n- Probe attempted: `{probe['attempted']}`\n\n"+
              f"Next action: {report['next_action']}\n")
    if args.json or not args.markdown:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
