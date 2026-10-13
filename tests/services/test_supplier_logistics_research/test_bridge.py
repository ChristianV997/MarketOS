"""Integration tests for the offline supplier-evidence bridge."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from backend.economics.kernel import CurrencyMismatchError, Money
from services.supplier_logistics_research import (
    build_offer_from_supplier_evidence,
    build_report_from_supplier_evidence,
)


GENERATED_AT = "2026-10-12T00:00:00Z"


def test_imported_supplier_evidence_flows_to_canonical_landed_cost_report(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    report = build_report_from_supplier_evidence(
        record,
        target_price=Money("50", "USD", source="operator_input", provenance="assumed", evidence_state="assumed"),
        generated_at=GENERATED_AT,
    )

    assert report.candidate_id == record.candidate_id
    assert len(report.landed_cost_scenarios) == 3
    base = next(item for item in report.landed_cost_scenarios if item.scenario_id == "base").result
    assert base.net_sales.amount == Decimal("50")
    assert base.product_cost.amount == Decimal("8.5")
    assert base.supplier_shipping.amount == Decimal("3.25")
    assert report.read_only is True and report.network_calls is False and report.mutated is False


def test_missing_shipping_stays_missing_in_kernel_evidence(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    record = replace(record, shipping_cost=None, field_provenance={**record.field_provenance, "shipping_cost": "unavailable"})
    report = build_report_from_supplier_evidence(
        record,
        target_price=Money("50", "USD", source="operator_input", provenance="assumed", evidence_state="assumed"),
        generated_at=GENERATED_AT,
    )

    scenario = report.landed_cost_scenarios[0].result
    assert report.offer.goods is not None
    assert report.offer.goods.shipping.supplier_shipping is None
    assert "supplier_shipping" in scenario.missing_inputs
    assert report.offer.goods.shipping.evidence.provenance == "unavailable"
    assert scenario.supplier_shipping.source.startswith("assumed_")
    assert scenario.supplier_shipping.evidence_state == "unknown"


def test_explicit_zero_shipping_is_not_missing(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    record = replace(record, shipping_cost=0.0, field_provenance={**record.field_provenance, "shipping_cost": "observed"})
    offer = build_offer_from_supplier_evidence(record)

    assert offer.goods is not None
    assert offer.goods.shipping.supplier_shipping is not None
    assert offer.goods.shipping.supplier_shipping.amount == Decimal("0.0")
    report = build_report_from_supplier_evidence(
        record,
        target_price=Money("50", "USD", source="operator_input", provenance="assumed", evidence_state="assumed"),
        generated_at=GENERATED_AT,
    )
    assert report.landed_cost_scenarios[0].result.supplier_shipping.amount == Decimal("0.0")


def test_shipping_currency_mismatch_fails_at_canonical_boundary(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    record = replace(record, shipping_currency="EUR")
    offer = build_offer_from_supplier_evidence(record)
    assert offer.quoted_price is not None
    assert offer.quoted_price.currency == "USD"
    assert offer.goods is not None
    assert offer.goods.shipping.supplier_shipping is not None
    assert offer.goods.shipping.supplier_shipping.currency == "EUR"
    with pytest.raises(CurrencyMismatchError):
        build_report_from_supplier_evidence(
            record,
            target_price=Money("50", "USD", source="operator_input", provenance="assumed", evidence_state="assumed"),
            generated_at=GENERATED_AT,
        )


def test_supplier_claim_is_preserved_but_not_promoted_to_verified(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path
    from services.supplier_logistics_research import controls

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    offer = build_offer_from_supplier_evidence(record)

    assert offer.price_evidence.provenance == "fixture"
    assert controls.is_verified(offer.price_evidence) is False
    assert offer.goods is not None
    assert offer.goods.moq_availability.minimum_order_quantity == record.moq
    assert offer.goods.moq_availability.available_quantity == record.inventory_quantity
    assert offer.goods.lead_time.minimum_days == record.delivery_min_days
    assert offer.goods.lead_time.maximum_days == record.delivery_max_days
    assert offer.goods.supplier_evidence.evidence_ref is not None
    assert offer.goods.supplier_evidence.evidence_ref.origin == record.warehouse_region
    assert offer.goods.supplier_evidence.evidence_ref.destination == record.destination_region


def test_stale_and_conflicting_import_metadata_remain_uncertain(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    stale = replace(record, evidence_mode="stale")
    conflicting = replace(record, warnings=("conflicting_supplier_offer",))

    stale_offer = build_offer_from_supplier_evidence(stale)
    conflicting_offer = build_offer_from_supplier_evidence(conflicting)

    assert stale_offer.price_evidence.provenance == "stale"
    assert stale_offer.price_evidence.quality == "stale"
    assert conflicting_offer.price_evidence.quality == "conflicting"
    assert conflicting_offer.price_evidence.evidence_ref is not None
    assert conflicting_offer.price_evidence.evidence_ref.human_confirmed is False


def test_destination_warehouse_and_supplier_facts_remain_candidate_bound(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    record = replace(record, warehouse_region="CN-SH", destination_region="MX-NL", fulfillment_method="direct freight")
    offer = build_offer_from_supplier_evidence(record)

    assert offer.goods is not None
    assert offer.goods.fulfillment_mode == "direct_freight"
    assert offer.goods.moq_availability.minimum_order_quantity == 1
    assert offer.goods.moq_availability.available_quantity == 420
    assert offer.goods.lead_time.minimum_days == 7
    assert offer.goods.lead_time.maximum_days == 12
    assert offer.goods.supplier_evidence.evidence_ref is not None
    assert offer.goods.supplier_evidence.evidence_ref.origin == "CN-SH"
    assert offer.goods.supplier_evidence.evidence_ref.destination == "MX-NL"
    assert offer.goods.supplier_evidence.evidence_ref.human_confirmed is False


def test_missing_logistics_facts_stay_unknown_and_blocked(offer_factory):
    from backend.adapters.research.supplier_feasibility import import_json
    from pathlib import Path

    record = import_json(Path(__file__).resolve().parents[2] / "fixtures" / "supplier_feasibility" / "cj_validation_pack_success.json", supplier="cj", source_type="cj_validation_pack_report")[0]
    record = replace(
        record,
        shipping_cost=None,
        shipping_currency=None,
        moq=None,
        inventory_status=None,
        inventory_quantity=None,
        warehouse_region="",
        destination_region="",
        delivery_min_days=None,
        delivery_max_days=None,
        fulfillment_method="",
        field_provenance={"unit_cost": "fixture"},
    )
    offer = build_offer_from_supplier_evidence(record)

    assert offer.goods is not None
    assert offer.goods.shipping.supplier_shipping is None
    assert offer.goods.shipping.evidence.quality == "missing"
    assert offer.goods.moq_availability.minimum_order_quantity is None
    assert offer.goods.moq_availability.available_quantity is None
    assert offer.goods.moq_availability.availability_status == "unknown"
    assert offer.goods.moq_availability.evidence.quality == "missing"
    assert offer.goods.lead_time.minimum_days is None
    assert offer.goods.lead_time.maximum_days is None
    assert offer.goods.lead_time.evidence.quality == "missing"
    assert offer.goods.fulfillment_mode == "unknown"
    assert offer.goods.logistics_evidence.quality == "missing"

    report = build_report_from_supplier_evidence(
        record,
        target_price=Money("50", "USD", source="operator_input", provenance="assumed", evidence_state="assumed"),
        generated_at=GENERATED_AT,
    )
    assert {entry.category for entry in report.risk_matrix} >= {
        "moq_availability",
        "lead_time",
        "logistics",
        "shipping_cost",
    }
    assert any("logistics: evidence is missing" in blocker for blocker in report.blockers)
    assert any("shipping_cost: evidence is missing" in blocker for blocker in report.blockers)


def test_normalized_cj_candidate_record_reaches_canonical_landed_cost_report(offer_factory):
    from backend.adapters.research.supplier_feasibility import normalize_record

    row = {
        "candidate_id": "candidate-espresso-1",
        "query": "Portable Espresso Maker",
        "supplier": "cj",
        "source_type": "cj_readonly_fixture",
        "evidence_mode": "fixture",
        "supplier_product_id": "cj-variant-1",
        "supplier_title": "Portable Espresso Maker",
        "supplier_sku": "CJ-ESP-1-BLK",
        "moq": 2,
        "unit_cost": 12.5,
        "currency": "USD",
        "shipping_cost": 4.71,
        "shipping_currency": "USD",
        "delivery_min_days": 2,
        "delivery_max_days": 5,
        "inventory_status": "in_stock",
        "inventory_quantity": 37,
        "warehouse_region": "United States Warehouse",
        "destination_region": "US",
        "fulfillment_method": "supplier_shipped",
        "field_provenance": {
            "unit_cost": "fixture",
            "shipping_cost": "fixture",
            "moq": "fixture",
            "inventory_quantity": "fixture",
            "delivery_min_days": "fixture",
            "delivery_max_days": "fixture",
        },
        "observed_at": "2027-01-15T08:00:00Z",
        "warnings": ["supplier_reliability_unknown_until_fulfillment_outcomes"],
    }
    record = normalize_record(row, default_supplier="cj", default_source_type="cj_readonly_fixture", mode="fixture")
    assert record is not None

    report = build_report_from_supplier_evidence(
        record,
        target_price=Money("50", "USD", source="operator_input", provenance="assumed", evidence_state="assumed"),
        generated_at=GENERATED_AT,
    )

    assert report.candidate_id == "candidate-espresso-1"
    assert len(report.landed_cost_scenarios) == 3
    assert report.offer.quoted_price is not None
    assert report.offer.quoted_price.currency == "USD"
    assert report.offer.goods is not None
    assert report.offer.goods.shipping.supplier_shipping is not None
    assert report.offer.goods.shipping.supplier_shipping.amount == Decimal("4.71")
    assert report.offer.goods.moq_availability.minimum_order_quantity == 2
    assert report.offer.goods.moq_availability.available_quantity == 37
    assert report.offer.goods.lead_time.minimum_days == 2
    assert report.offer.goods.lead_time.maximum_days == 5
    assert report.offer.goods.fulfillment_mode == "unknown"
    evidence_ref = report.offer.goods.supplier_evidence.evidence_ref
    assert evidence_ref is not None
    assert evidence_ref.origin == "United States Warehouse"
    assert evidence_ref.destination == "US"
    assert evidence_ref.human_confirmed is False
