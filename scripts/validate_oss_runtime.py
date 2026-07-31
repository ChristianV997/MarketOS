"""Read-only OSS runtime validation report.

This harness never downloads repositories or performs live commerce/publishing
actions. It validates the local inventory, optional dependency state, adapter
health, and deterministic dry-run boundaries.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scripts.validate_oss_inventory import INVENTORY, validate_inventory
except ModuleNotFoundError:  # direct ``python scripts/validate_oss_runtime.py``
    from validate_oss_inventory import INVENTORY, validate_inventory

def _health_record(provider: Any) -> dict[str, Any]:
    started = time.perf_counter()
    health = provider.health()
    return {
        "name": health.name,
        "configured": health.configured,
        "reachable": health.reachable,
        "capabilities": list(health.capabilities),
        "detail": health.detail,
        "probe_latency_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def build_report(inventory: Path = INVENTORY) -> dict[str, Any]:
    from backend.adapters.research.crawl4ai import Crawl4AIResearchAdapter
    from backend.agents.pydantic_boundary import PydanticAIAgentProvider
    from backend.integrations.browser_use_worker import BrowserUseWorker
    from backend.integrations.medusa import MedusaCommerceAdapter
    from backend.integrations.mercado_pago_mx import MercadoPagoMxPaymentAdapter
    from backend.integrations.n8n import N8nAutomationAdapter
    from backend.integrations.postiz import PostizPublisherAdapter
    from backend.integrations.stripe_mx import StripeMxPaymentAdapter
    from backend.integrations.woocommerce import WooCommerceCommerceAdapter
    from backend.contracts.adapters import SidecarContext

    providers = [
        MedusaCommerceAdapter(), Crawl4AIResearchAdapter(), BrowserUseWorker(),
        PostizPublisherAdapter(), N8nAutomationAdapter(), PydanticAIAgentProvider(),
        WooCommerceCommerceAdapter(), StripeMxPaymentAdapter(), MercadoPagoMxPaymentAdapter(),
    ]
    return {
        "inventory": str(inventory),
        "inventory_errors": validate_inventory(inventory),
        "read_only": True,
        "providers": [_health_record(provider) for provider in providers],
        "dry_run_boundaries": {
            "medusa": MedusaCommerceAdapter().create_order({}, context=SidecarContext()),
            "postiz": PostizPublisherAdapter().publish({}, context=SidecarContext()),
            "n8n": N8nAutomationAdapter().trigger("alerts", {}, context=SidecarContext()),
            "woocommerce": WooCommerceCommerceAdapter().create_order({}, context=SidecarContext()),
            "stripe_mx": StripeMxPaymentAdapter().handle_webhook({}, context=SidecarContext()),
            "mercado_pago_mx": MercadoPagoMxPaymentAdapter().handle_webhook({}, context=SidecarContext()),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=INVENTORY)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    report = build_report(args.inventory)
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"OSS runtime validation: {'PASS' if not report['inventory_errors'] else 'FAIL'}")
        for provider in report["providers"]:
            print(f"- {provider['name']}: configured={provider['configured']} reachable={provider['reachable']} latency_ms={provider['probe_latency_ms']}")
        for error in report["inventory_errors"]:
            print(f"ERROR: {error}")
    return 0 if not report["inventory_errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
