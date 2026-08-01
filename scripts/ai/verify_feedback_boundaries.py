"""Run credential-free checks for MarketOS's canonical feedback boundary."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Support both ``python -m ...`` and direct execution from any cwd.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.commerce.feedback import observation_from_metrics, observation_from_order
from backend.commerce.observation_ledger import FeedbackObservationLedger


def run_checks() -> dict[str, bool]:
    checks: dict[str, bool] = {}
    live = observation_from_metrics(
        observation_id="verify:tiktok:c1:1",
        source="tiktok",
        campaign_id="c1",
        product_id="p1",
        spend=10,
        revenue=25,
    )
    checks["live_metrics_normalize"] = live is not None and live.quality.is_live_attributed
    checks["spend_only_rejected"] = observation_from_metrics(
        observation_id="verify:meta:c1:1", source="meta", campaign_id="c1", spend=10
    ) is None
    checks["unattributed_order_rejected"] = observation_from_order(
        {"id": "order-1", "total_price": 20}, source="shopify"
    ) is None
    checks["explicit_order_attributed"] = observation_from_order(
        {"id": "order-2", "total_price": 20, "metadata": {"marketos_campaign_id": "c1"}},
        source="shopify",
    ) is not None

    with tempfile.TemporaryDirectory(prefix="marketos-feedback-") as directory:
        db = str(Path(directory) / "observations.sqlite3")
        ledger = FeedbackObservationLedger(db)
        checks["ledger_claims_once"] = bool(live and ledger.claim(live) and not ledger.claim(live))
        ledger.close()
        restarted = FeedbackObservationLedger(db)
        checks["ledger_survives_restart"] = bool(live and not restarted.claim(live))
        restarted.close()
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    args = parser.parse_args()
    checks = run_checks()
    report = {"status": "ok" if all(checks.values()) else "failed", "checks": checks}
    print(json.dumps(report, indent=2) if args.json else report["status"])
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
