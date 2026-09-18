from decimal import Decimal

from backend.economics import Money, canonical_json
from evaluation.companyos.service_catalog import (
    catalog_to_dict,
    default_service_catalog,
    package_map,
    service_package_economics,
)


def test_existing_catalog_exposes_canonical_service_aliases_without_a_second_catalog():
    packages = default_service_catalog()
    mapped = package_map(packages)
    assert len(packages) == 11
    assert mapped["product-validation-sprint"] is mapped["product-opportunity-report"]
    assert mapped["unit-economics-cac-roas-diagnostic"].canonical_name == "Unit Economics + CAC/ROAS Diagnostic"
    assert mapped["launch-draft-pack"].canonical_name == "Launch Draft Pack"
    assert mapped["managed-acquisition-cro"].canonical_name == "Managed Acquisition/CRO"


def test_catalog_price_and_service_economics_are_typed_and_deterministic():
    package = next(item for item in default_service_catalog() if item.package_id == "launch-draft-pack")
    assert package.price_min_money == Money("750", "USD", source="service_catalog", provenance="assumed")
    result = service_package_economics(
        package,
        price=Money("1000", "USD"),
        ad_spend=Money("5000", "USD"),
        roas_before=Decimal("1"),
        roas_after=Decimal("2"),
        cac_before=Money("30", "USD"),
        cac_after=Money("20", "USD"),
        capacity_hours=Decimal("40"),
    )
    assert result.incremental_contribution.amount == Decimal("2900.00")
    assert result.orders_required_to_recover_fee == Decimal("100")
    assert canonical_json(catalog_to_dict(default_service_catalog())) == canonical_json(catalog_to_dict(default_service_catalog()))
