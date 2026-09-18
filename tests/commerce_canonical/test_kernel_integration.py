from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from backend.economics.kernel import (
    CurrencyMismatchError,
    EvidenceRef,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
)
from evaluation.commerce.canonical import BusinessModel
from evaluation.commerce.kernel_integration import (
    CANONICAL_KERNEL_MODULE,
    AuthorityInventory,
    client_safe_projection,
    compatibility_unit_economics,
    economics_payload,
    replay_fingerprint,
    service_package_to_economics,
    supplier_offer_to_economics,
)
from evaluation.companyos.service_engagement import build_service_engagement


def _usd(amount: str, *, state: str = "observed") -> Money:
    return Money(amount, "USD", source="fixture", provenance="fixture", evidence_state=state)


def test_duplicate_authority_is_not_reintroduced_by_integration_module():
    inventory = AuthorityInventory()
    assert inventory.owns_money_arithmetic == CANONICAL_KERNEL_MODULE
    assert inventory.owns_commerce_mapping == "evaluation.commerce.kernel_integration"
    source = Path("evaluation/commerce/kernel_integration.py").read_text(encoding="utf-8")
    assert "class Money" not in source
    assert "def calculate_unit_economics" not in source


def test_canonical_import_ownership_is_the_248_kernel():
    import backend.economics.kernel as kernel
    import backend.economics as package

    assert kernel.__name__ == CANONICAL_KERNEL_MODULE
    assert package.Money is kernel.Money
    assert package.calculate_unit_economics is kernel.calculate_unit_economics


def test_currency_mismatch_and_missing_fx_metadata_fail_closed():
    lane = MarketLane("mx-lane", "MX", "MX", "MX-CDMX", "MX", currency="MXN")
    with pytest.raises(CurrencyMismatchError):
        supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=lane)
    with pytest.raises(Exception):
        _usd("10").convert("MXN", exchange_rate="17", exchange_rate_timestamp="", uncertainty="0.01", source="fixture")


def test_supplier_evidence_and_reserves_propagate():
    evidence = EvidenceRef("ev-supplier", source_type="supplier_quote", evidence_state="observed")
    lane = MarketLane("us-lane", "US", "US", "US-TX", "US", currency="USD")
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=_usd("4"),
        return_rate="0.02",
        warranty_rate="0.01",
        evidence_refs=(evidence,),
    )
    result = supplier_offer_to_economics(
        price=_usd("50"),
        product_cost=_usd("20"),
        lane=lane,
        assumptions=assumptions,
        evidence_refs=(evidence,),
    )
    payload = economics_payload(result)
    assert payload["kernel_authority"] == CANONICAL_KERNEL_MODULE
    assert "supplier_shipping" not in result.missing_inputs
    assert result.return_reserve.amount > Decimal("0")
    assert any(ref.evidence_id == "ev-supplier" for ref in result.evidence_refs)


def test_missing_costs_stay_missing_not_silent_zero_authority():
    lane = MarketLane("us-lane", "US", "US", "US-TX", "US", currency="USD")
    result = supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=lane)
    assert "supplier_shipping" in result.missing_inputs
    assert result.supplier_shipping.amount == Decimal("0")
    assert result.supplier_shipping.source != "observed"


def test_service_economics_propagate_and_reject_thin_data():
    fee = _usd("1500")
    with pytest.raises(Exception):
        service_package_to_economics(package_id="managed-marketing-cro", service_fee=fee, inputs={})
    result = service_package_to_economics(
        package_id="managed-marketing-cro",
        service_fee=fee,
        inputs={
            "ad_spend": _usd("10000"),
            "contribution_margin": Decimal("0.40"),
            "roas_before": Decimal("1.8"),
            "roas_after": Decimal("2.3"),
            "cac_before": _usd("25"),
            "cac_after": _usd("18"),
            "delivery_hours": Decimal("24"),
            "capacity_hours": Decimal("160"),
        },
    )
    assert result.incremental_contribution.amount == Decimal("500")
    thin = build_service_engagement(
        "eng-thin", "Managed Acquisition and CRO", "Thin Client", service_fee=fee, inputs={}
    )
    assert thin.to_dict()["status"] == "data_inadequate"
    assert thin.economics is None


def test_compatibility_api_and_client_safe_export():
    payload = compatibility_unit_economics(selling_price="80", unit_cost="30", currency="USD", shipping_cost="5")
    assert payload["compatibility"]["currency"] == "USD"
    safe = client_safe_projection(
        {**payload, "internal_prompt": "never", "heuristic": "hidden", "source_code": "nope"}
    )
    blob = str(safe).lower()
    assert "never" not in blob
    assert "hidden" not in blob
    assert safe["record_kind"] == "planning_record"
    assert safe["live_actions_taken"] is False


def test_deterministic_replay_and_no_live_execution():
    lane = MarketLane("us-lane", "US", "US", "US-TX", "US", currency="USD")
    first = economics_payload(supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=lane))
    second = economics_payload(supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=lane))
    assert replay_fingerprint(first) == replay_fingerprint(second)
    assert first["live_actions_taken"] is False
    assert BusinessModel.RETAIL_MARGIN.value == "retail_margin"
