from decimal import Decimal

import pytest

from backend.economics.kernel import Money

from evaluation.companyos.service_catalog import default_service_catalog
from evaluation.companyos.service_engagement import (
    build_service_engagement,
    canonical_client_services,
    catalog_with_canonical_services,
)

_FULL_INPUTS = {
    "ad_spend": Money("10000", "USD"),
    "contribution_margin": Decimal("0.40"),
    "roas_before": Decimal("1.8"),
    "roas_after": Decimal("2.3"),
    "cac_before": Money("25", "USD"),
    "cac_after": Money("18", "USD"),
    "delivery_hours": Decimal("24"),
    "capacity_hours": Decimal("160"),
}


def test_four_named_services_alias_onto_existing_or_new_packages():
    services = canonical_client_services()
    names = [item.canonical_name for item in services]
    assert names == [
        "Product Validation Sprint",
        "Unit Economics + CAC/ROAS Diagnostic",
        "Launch Draft Pack",
        "Managed Acquisition and CRO",
    ]


def test_original_catalog_is_untouched_and_still_has_eleven_packages():
    # This module must not mutate evaluation.companyos.service_catalog; the
    # financial-kernel lane (PR #248) is separately extending that file.
    assert len(default_service_catalog()) == 11


def test_catalog_with_canonical_services_is_additive_not_destructive():
    extended = catalog_with_canonical_services()
    assert len(extended) == 12
    ids = {package.package_id for package in extended}
    assert "unit-economics-cac-roas-diagnostic" in ids
    assert "product-opportunity-report" in ids  # original entries preserved


def test_insufficient_client_data_produces_data_inadequate_not_a_guess():
    engagement = build_service_engagement(
        "eng-1", "Managed Acquisition and CRO", "Client Co",
        service_fee=Money("1500", "USD"), inputs={},
    )
    result = engagement.to_dict()
    assert result["status"] == "data_inadequate"
    assert result["economics"] is None
    assert "missing_ad_spend" in result["reasons"]


def test_partial_client_data_is_still_data_inadequate():
    partial = dict(_FULL_INPUTS)
    del partial["roas_after"]
    engagement = build_service_engagement(
        "eng-2", "Managed Acquisition and CRO", "Client Co",
        service_fee=Money("1500", "USD"), inputs=partial,
    )
    assert engagement.to_dict()["status"] == "data_inadequate"


def test_full_client_data_computes_incremental_contribution_and_recovery():
    engagement = build_service_engagement(
        "eng-3", "Managed Acquisition and CRO", "Client Co",
        service_fee=Money("1500", "USD"), inputs=_FULL_INPUTS,
    )
    result = engagement.to_dict()
    assert result["status"] == "ready_for_client_service"
    economics = result["economics"]
    # incremental_contribution = ad_spend * margin * (roas_after - roas_before) - fee
    # = 10000 * 0.40 * (2.3 - 1.8) - 1500 = 500
    assert Decimal(economics["incremental_contribution"]["amount"]) == Decimal("500")
    # orders_required_to_recover_fee = fee / (cac_before - cac_after) = 1500 / 7
    assert Decimal(economics["orders_required_to_recover_fee"]) == Decimal("1500") / Decimal("7")


def test_unknown_canonical_service_name_is_rejected():
    with pytest.raises(ValueError):
        build_service_engagement(
            "eng-4", "Not A Real Service", "Client Co",
            service_fee=Money("100", "USD"), inputs=_FULL_INPUTS,
        )
