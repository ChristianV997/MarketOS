#!/usr/bin/env python3
"""Dry-run service-delivery plane runner.

Creates offline planning records and client-safe projections only.
Does not send email, invoice, publish, or call providers.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.companyos.service_delivery_export import (  # noqa: E402
    project_launch_draft,
    project_managed_acquisition,
    project_product_validation,
    project_unit_economics,
)
from evaluation.companyos.service_delivery_plane import (  # noqa: E402
    refuse_live_action,
    replay_fingerprint,
)


INTAKE = {
    "orders": 120,
    "revenue": "8400",
    "cac": "18",
    "contribution_margin": "0.35",
    "period_start": "2026-08-01",
    "period_end": "2026-08-31",
    "channel": "paid_social",
    "returns_refunds": "4",
    "ad_spend": "2000",
    "offer_id": "offer-alpha",
    "currency": "USD",
    "market": "US",
    "roas_before": "1.4",
    "roas_after": "2.1",
    "cac_before": "22",
    "cac_after": "16",
    "evidence_set": ("90-day order extract",),
    "evidence_references": ("ev-orders-001",),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    kwargs = {
        "client_id": "client-demo",
        "workspace_id": "ws-client-demo",
        "scope": "dry-run-v4",
        "intake": INTAKE,
        "fee": "900",
        "planned_hours": "10",
        "requesting_workspace": "ws-client-demo",
    }
    reports = {
        "product_validation": project_product_validation(**kwargs),
        "unit_economics": project_unit_economics(**kwargs),
        "launch_draft": project_launch_draft(**kwargs),
        "managed_acquisition": project_managed_acquisition(**kwargs),
    }
    live = refuse_live_action("launch_ad_experiment", workspace_id="ws-client-demo")
    payload = {
        "schema": "MarketOS.ServiceDeliveryDryRun.v4",
        "record_kind": "planning_record",
        "packages": {name: report["package_id"] for name, report in reports.items()},
        "replay_equal": all(
            replay_fingerprint(report) == replay_fingerprint(report) for report in reports.values()
        ),
        "live_action": live,
        "reports": reports,
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str) if args.json else json.dumps(payload, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
