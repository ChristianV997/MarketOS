"""Run one bounded, offline supplier landed-cost assessment.

The command consumes an existing sanitized supplier JSON/CSV import, selects
one candidate, applies an explicit selling-price assumption, and delegates
the assessment to ``services.supplier_logistics_research``.  It never ranks
suppliers, calls a provider, writes artifacts, or authorizes a purchase.
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.adapters.research.supplier_feasibility import SupplierImportError, import_csv, import_json  # noqa: E402
from backend.economics.kernel import Money  # noqa: E402
from services.supplier_logistics_research import build_report_from_supplier_evidence  # noqa: E402

SCHEMA = "MarketOS.SupplierLandedCostFeasibilityCLI.v1"


def _decimal(value: str, field_name: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(f"invalid {field_name}")
    return result


def _load_records(path: Path, input_format: str, supplier: str):
    selected = input_format
    if selected == "auto":
        selected = "csv" if path.suffix.lower() == ".csv" else "json"
    if selected == "csv":
        return import_csv(path, supplier=supplier, source_type="manual_csv_import")
    return import_json(path, supplier=supplier, source_type="fixture_demo")


def _select_record(records, candidate_id: str | None):
    if candidate_id:
        matches = [record for record in records if record.candidate_id == candidate_id]
    elif len(records) == 1:
        matches = list(records)
    else:
        raise ValueError("candidate_id is required when the input has zero or multiple records")
    if len(matches) != 1:
        raise ValueError("candidate_id must resolve to exactly one supplier evidence record")
    return matches[0]


def _payload(record, report, target_price: Money) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "candidate_id": record.candidate_id,
        "target_price": target_price.to_dict(),
        "supplier_context": {
            "supplier": record.supplier,
            "supplier_product_id": record.supplier_product_id,
            "warehouse_region": record.warehouse_region or None,
            "destination_region": record.destination_region or None,
            "minimum_order_quantity": record.moq,
            "available_quantity": record.inventory_quantity,
            "delivery_window_days": [record.delivery_min_days, record.delivery_max_days],
            "evidence_mode": record.evidence_mode,
            "field_provenance": dict(sorted(record.field_provenance.items())),
        },
        "assessment": report.to_dict(),
        "safety": {
            "offline": True,
            "read_only": True,
            "network_calls": False,
            "mutated": False,
            "purchase_authorized": False,
            "supplier_verified": False,
            "launch_authorized": False,
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    assessment = payload["assessment"]
    context = payload["supplier_context"]
    next_actions = ", ".join(f"`{item['action_id']}`" for item in assessment["next_actions"]) or "none"
    lines = [
        "# Supplier Landed-Cost Feasibility",
        "",
        "> **OFFLINE ASSESSMENT** - this report uses sanitized local evidence and explicit assumptions. It is not a purchase, supplier-verification, or launch recommendation.",
        "",
        f"- Candidate: `{payload['candidate_id']}`",
        f"- Supplier: `{context['supplier']}`",
        f"- Evidence mode: `{context['evidence_mode']}`",
        f"- Warehouse: `{context['warehouse_region'] or 'unknown'}`",
        f"- Destination: `{context['destination_region'] or 'unknown'}`",
        f"- MOQ: `{context['minimum_order_quantity'] if context['minimum_order_quantity'] is not None else 'unknown'}`",
        f"- Available quantity: `{context['available_quantity'] if context['available_quantity'] is not None else 'unknown'}`",
        f"- Delivery window: `{context['delivery_window_days']}`",
        "",
        "## Assessment",
        "",
        f"- Status: `{assessment['status']}`",
        f"- Blockers: {', '.join(f'`{item}`' for item in assessment['blockers']) or 'none'}",
        f"- Next actions: {next_actions}",
        "",
        "## Landed-Cost Scenarios",
        "",
        "| Scenario | Currency | Product cost | Supplier shipping | Contribution before CAC | Missing inputs |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for item in assessment["landed_cost_scenarios"]:
        result = item["result"]
        lines.append(
            f"| {item['scenario_id']} | {result['currency']} | {result['product_cost']['amount']} | "
            f"{result['supplier_shipping']['amount']} | {result['contribution_before_cac']['amount']} | "
            f"{', '.join(result['missing_inputs']) or 'none'} |"
        )
    lines += [
        "",
        "## Safety",
        "",
        "- No provider, supplier, order, payment, inventory, publishing, or launch action is reachable.",
        "- Fixture/manual/derived values remain evidence-labeled and are not supplier-live proof.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline supplier landed-cost feasibility assessment")
    parser.add_argument("--input", required=True, type=Path, help="sanitized local supplier JSON or CSV")
    parser.add_argument("--input-format", choices=("auto", "json", "csv"), default="auto")
    parser.add_argument("--supplier", default="cj")
    parser.add_argument("--candidate-id")
    parser.add_argument("--target-price", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--generated-at", required=True, help="explicit timestamp for deterministic output")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    args = parser.parse_args(argv)
    try:
        records = _load_records(args.input, args.input_format, args.supplier)
        record = _select_record(records, args.candidate_id)
        target_price = Money(
            _decimal(args.target_price, "target price"),
            args.currency,
            source="operator_input",
            provenance="assumed",
            evidence_state="assumed",
        )
        report = build_report_from_supplier_evidence(record, target_price=target_price, generated_at=args.generated_at)
        payload = _payload(record, report, target_price)
    except (OSError, ValueError, InvalidOperation, SupplierImportError) as exc:
        parser.error(str(exc))
    print(render_markdown(payload) if args.format == "markdown" else json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
