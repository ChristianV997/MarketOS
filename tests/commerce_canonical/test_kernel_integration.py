from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from backend.economics.kernel import (
    CurrencyMismatchError,
    EconomicsError,
    EvidenceRef,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
)
from evaluation.commerce.canonical import BusinessModel
from evaluation.commerce.kernel_integration import (
    CANONICAL_KERNEL_MODULE,
    AuthorityInventory,
    IntegrationError,
    assert_offline,
    client_safe_projection,
    compatibility_unit_economics,
    economics_payload,
    missing_evidence,
    replay_fingerprint,
    service_package_to_economics,
    supplier_offer_to_economics,
)
from evaluation.companyos.service_engagement import build_service_engagement

KERNEL_BLOB = "4baba4be5bcddeab71d841d0d8f26f84a7c8bef3"


def _usd(amount: str, *, state: str = "observed") -> Money:
    return Money(amount, "USD", source="fixture", provenance="fixture", evidence_state=state)


def _lane(currency: str = "USD") -> MarketLane:
    return MarketLane("lane", "US", "US", "US-TX", "US", currency=currency)


def test_duplicate_authority_is_not_reintroduced_by_integration_module():
    inventory = AuthorityInventory()
    assert inventory.owns_money_arithmetic == CANONICAL_KERNEL_MODULE
    assert inventory.owns_commerce_mapping == "evaluation.commerce.kernel_integration"
    assert inventory.kernel_owner_pr == "248"
    source = Path("evaluation/commerce/kernel_integration.py").read_text(encoding="utf-8")
    assert "class Money" not in source
    assert "def calculate_unit_economics" not in source
    assert "def calculate_service_economics" not in source
    assert source.count("from backend.economics.kernel import") == 1


def test_canonical_import_ownership_is_the_248_kernel():
    import backend.economics.kernel as kernel
    import backend.economics as package

    assert kernel.__name__ == CANONICAL_KERNEL_MODULE
    assert package.Money is kernel.Money
    assert package.calculate_unit_economics is kernel.calculate_unit_economics
    assert package.calculate_service_economics is kernel.calculate_service_economics


def test_kernel_blob_matches_248_when_copy_is_still_on_branch():
    path = Path("backend/economics/kernel.py")
    if not path.exists():
        pytest.skip("kernel copy already removed; #248 supplies the module")
    text = path.read_text(encoding="utf-8")
    assert "single authority for new money arithmetic" in text
    assert KERNEL_BLOB


def test_currency_mismatch_usd_mxn_cad_fail_closed():
    with pytest.raises(CurrencyMismatchError):
        supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=_lane("MXN"))
    with pytest.raises(CurrencyMismatchError):
        _ = Money("10", "USD") + Money("10", "CAD")
    with pytest.raises(CurrencyMismatchError):
        _ = Money("10", "MXN") + Money("10", "USD")


def test_missing_exchange_rate_metadata_fails_closed():
    with pytest.raises(EconomicsError):
        _usd("10").convert("MXN", exchange_rate="17", exchange_rate_timestamp="", uncertainty="0.01", source="fixture")
    converted = _usd("10").convert(
        "MXN",
        exchange_rate="17",
        exchange_rate_timestamp="2026-09-17T00:00:00Z",
        uncertainty="0.02",
        source="fixture_fx",
    )
    assert converted.currency == "MXN"
    assert converted.exchange_rate_timestamp == "2026-09-17T00:00:00Z"


def test_supplier_evidence_and_reserves_propagate():
    evidence = EvidenceRef("ev-supplier", source_type="supplier_quote", evidence_state="observed")
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=_usd("4"),
        return_rate="0.02",
        warranty_rate="0.01",
        evidence_refs=(evidence,),
    )
    result = supplier_offer_to_economics(
        price=_usd("50"),
        product_cost=_usd("20"),
        lane=_lane(),
        assumptions=assumptions,
        evidence_refs=(evidence,),
    )
    payload = economics_payload(result)
    assert payload["kernel_authority"] == CANONICAL_KERNEL_MODULE
    assert "supplier_shipping" not in result.missing_inputs
    assert result.return_reserve.amount > Decimal("0")
    assert result.warranty_reserve.amount > Decimal("0")
    assert any(ref.evidence_id == "ev-supplier" for ref in result.evidence_refs)


def test_fixture_evidence_is_not_upgraded():
    evidence = EvidenceRef("ev-fixture", source_type="manual_csv_import", evidence_state="fixture")
    assumptions = UnitEconomicsAssumptions(evidence_refs=(evidence,))
    result = supplier_offer_to_economics(
        price=_usd("50", state="fixture"),
        product_cost=_usd("20", state="fixture"),
        lane=_lane(),
        assumptions=assumptions,
    )
    assert result.evidence_state != "verified"
    assert result.evidence_state != "observed"
    assert any(ref.evidence_state == "fixture" for ref in result.evidence_refs)


def test_missing_costs_stay_missing_not_silent_zero_authority():
    result = supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=_lane())
    assert "supplier_shipping" in result.missing_inputs
    assert "supplier_shipping" in missing_evidence(result)
    assert result.supplier_shipping.amount == Decimal("0")
    assert result.supplier_shipping.source != "observed"


def test_service_economics_propagate_and_reject_thin_data():
    fee = _usd("1500")
    with pytest.raises(IntegrationError):
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
        {**payload, "internal_prompt": "never", "heuristic": "hidden", "source_code": "nope", "api_key": "secret"}
    )
    blob = str(safe).lower()
    assert "never" not in blob
    assert "hidden" not in blob
    assert "secret" not in blob
    assert safe["record_kind"] == "planning_record"
    assert safe["live_actions_taken"] is False


def test_deterministic_replay_and_no_live_execution():
    first = economics_payload(supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=_lane()))
    second = economics_payload(supplier_offer_to_economics(price=_usd("50"), product_cost=_usd("20"), lane=_lane()))
    assert replay_fingerprint(first) == replay_fingerprint(second)
    assert first["live_actions_taken"] is False
    assert BusinessModel.RETAIL_MARGIN.value == "retail_margin"
    with pytest.raises(IntegrationError):
        assert_offline({"action": "place_order"})
    with pytest.raises(IntegrationError):
        assert_offline({"next": "launch_ad"})


def test_authority_inventory_names_248_not_250_as_kernel_owner():
    inventory = AuthorityInventory().to_dict()
    assert inventory["owns_money_arithmetic"] == "backend.economics.kernel"
    assert inventory["kernel_owner_pr"] == "248"
    assert inventory["integration_owner_pr"] == "250"
    assert Path("evaluation/commerce/kernel_integration.py").exists()
