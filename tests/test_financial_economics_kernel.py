from dataclasses import replace
from decimal import Decimal

import pytest

from backend.economics import (
    CurrencyMismatchError,
    EconomicsError,
    EvidenceRef,
    MarketLane,
    Money,
    UnitEconomicsAssumptions,
    calculate_scenarios,
    calculate_service_economics,
    calculate_unit_economics,
    canonical_json,
    incremental_contribution,
    orders_required_to_recover_fee,
    sensitivity_matrix,
)


def _money(amount: str, currency: str = "MXN", evidence: EvidenceRef | None = None, *, tax: str = "unknown") -> Money:
    return Money(amount, currency, source="fixture", provenance="fixture", evidence_ref=evidence, tax_inclusion_state=tax)


def test_money_uses_exact_decimal_arithmetic_and_round_trips():
    value = _money("0.10") + _money("0.20")
    assert value.amount == Decimal("0.30")
    restored = Money.from_dict(value.to_dict())
    assert restored.amount == Decimal("0.30") and restored.currency == "MXN"


@pytest.mark.parametrize("currency", ["MXN", "USD", "CAD"])
def test_required_currencies_are_supported(currency):
    assert Money("1.00", currency).currency == currency


def test_currency_mixing_requires_explicit_fx_evidence():
    with pytest.raises(CurrencyMismatchError):
        _ = _money("1", "MXN") + _money("1", "USD")
    converted = _money("100", "MXN").convert(
        "USD", exchange_rate="0.05", exchange_rate_timestamp="2026-09-16T00:00:00Z",
        uncertainty="0.01", source="fixture_fx",
    )
    assert converted.amount == Decimal("5.00")
    with pytest.raises(EconomicsError, match="exchange rate timestamp required"):
        _money("1", "MXN").convert("USD", exchange_rate="0.05", exchange_rate_timestamp="", uncertainty="0.01", source="fixture_fx")


def test_evidence_unknown_is_not_promoted_to_live_or_zero():
    evidence = EvidenceRef("e-unknown")
    assert evidence.evidence_state == "unknown"
    assert evidence.to_dict()["confidence"] == "unknown"
    result = calculate_unit_economics(_money("10"), _money("5"))
    assert result.evidence_state == "unknown"
    assert "supplier_shipping" in result.missing_inputs


def test_lane_rejects_invalid_identifiers_and_mismatched_fee_currency():
    with pytest.raises(EconomicsError):
        MarketLane("lane\nunsafe", "CN", "CN", "fixture-warehouse", "MX")
    with pytest.raises(CurrencyMismatchError):
        MarketLane("mx", "CN", "CN", "fixture-warehouse", "MX", currency="MXN", brokerage_fee=_money("1", "USD"))


def test_full_lane_economics_is_exact_and_evidence_bound():
    evidence = EvidenceRef("lane-evidence", source_type="fixture", evidence_state="verified", human_confirmed=True)
    lane = MarketLane(
        "cn-mx", "CN", "CN", "fixture-warehouse", "MX", destination_region="JAL",
        currency="MXN", tax_rate="0.16", duty_rate="0.05", brokerage_fee=_money("3", evidence=evidence),
        payment_fee_rate="0.03", platform_fee_rate="0.02", marketplace_fee_rate="0.015",
        return_destination="MX", delivery_promise="7-14 days", support_language="es",
        marketplace_permissions=("own_store",), compliance=("fixture_review",), evidence_refs=(evidence,),
        tax_inclusion_state="exclusive",
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=_money("5", evidence=evidence),
        domestic_shipping=_money("3", evidence=evidence),
        international_shipping=_money("2", evidence=evidence),
        payment_fee_fixed=_money("1", evidence=evidence),
        platform_fee_fixed=_money("0", evidence=evidence),
        return_rate="0.02", defect_rate="0.01", warranty_rate="0.005", support_reserve_rate="0.005",
        chargeback_rate="0.003", fx_reserve_rate="0.01", affiliate_fee_rate="0.01",
        tax_rate="0.16", duty_rate="0.05", payment_fee_rate="0.03", platform_fee_rate="0.02",
        marketplace_fee_rate="0.015", discount_rate="0", cac=_money("15", evidence=evidence),
        refund_lag_days="12", target_margin_rate="0.20", evidence_refs=(evidence,),
    )
    result = calculate_unit_economics(_money("100", evidence=evidence, tax="exclusive"), _money("20", evidence=evidence), lane=lane, assumptions=assumptions)
    assert result.contribution_before_cac.amount == Decimal("37.279")
    assert result.contribution_after_cac.amount == Decimal("22.279")
    assert result.tax.amount == Decimal("16.00")
    assert result.duty.amount == Decimal("1.500")
    assert result.refund_lag_exposure.amount == Decimal("0.80000")
    assert result.expected_return_cost == result.return_reserve
    assert result.refund_loss == result.return_reserve
    assert result.to_dict()["refund_loss"]["amount"] == "2.00"
    assert result.evidence_state == "verified"
    assert result.missing_inputs == ()


def test_tax_inclusive_price_does_not_charge_tax_twice():
    result = calculate_unit_economics(
        _money("100", tax="inclusive"), _money("20"),
        assumptions=UnitEconomicsAssumptions(tax_rate="0.16"),
    )
    assert result.tax.amount == Decimal("0")


def test_scenarios_and_sensitivity_are_deterministic():
    price, cost = _money("100"), _money("20")
    assumptions = UnitEconomicsAssumptions(supplier_shipping=_money("10"), cac=_money("10"), return_rate="0.05")
    scenarios = calculate_scenarios(price, cost, assumptions=assumptions)
    assert tuple(scenarios) == ("base", "downside", "upside")
    sensitivity = sensitivity_matrix(
        price,
        cost,
        {"cac": ["10", "20"], "price": ["90", "100"], "supplier_cost": ["20", "25"], "shipping": ["10", "12"], "fx": ["0", "0.05"], "conversion": ["0.05", "0.10"], "returns": ["0.05", "0.10"], "defects": ["0", "0.02"], "discounts": ["0", "0.05"], "marketplace_fees": ["0", "0.03"]},
        assumptions=replace(assumptions, ad_spend=_money("1000"), cac=None, conversion_rate="0.10"),
    )
    assert len(sensitivity["cac"]) == 2 and sensitivity["price"][1].net_sales.amount == Decimal("100")
    assert set(sensitivity) >= {"supplier_cost", "shipping", "fx", "conversion", "returns", "defects", "discounts", "marketplace_fees"}
    assert canonical_json(scenarios) == canonical_json(scenarios)


def test_lane_aliases_preserve_full_market_vocabulary():
    lane = MarketLane("cn-mx", "CN", "CN", "fixture-warehouse", "MX", currency="MXN")
    assert lane.origin_country == "CN"
    assert lane.ship_from_country == "CN"
    assert lane.to_dict()["origin_country"] == "CN"
    assert lane.to_dict()["ship_from_country"] == "CN"


def test_service_economics_uses_the_requested_formulas_and_capacity_state():
    fee = _money("100", "USD")
    spend = _money("1000", "USD")
    before = _money("20", "USD")
    after = _money("15", "USD")
    assert incremental_contribution(spend, "0.40", "2.5", "2", fee).amount == Decimal("100")
    assert orders_required_to_recover_fee(fee, before, after) == Decimal("20")
    assert orders_required_to_recover_fee(fee, before, before) is None
    result = calculate_service_economics(
        "unit-economics-cac-roas-diagnostic", fee, ad_spend=spend, contribution_margin="0.40",
        roas_before="2", roas_after="2.5", cac_before=before, cac_after=after,
        delivery_hours="10", capacity_hours="40", delivery_cost=Money("20", "USD"),
        tooling_cost=Money("10", "USD"), refund_revision_reserve=Money("5", "USD"),
        target_monthly_contribution=Money("1000", "USD"), client_value_created=Money("500", "USD"),
        minimum_acceptable_value_multiple="3",
    )
    assert result.incremental_contribution.amount == Decimal("100")
    assert result.capacity_utilization == Decimal("0.25")
    assert result.contribution.amount == Decimal("65")
    assert result.contribution_per_hour.amount == Decimal("6.5")
    assert result.maximum_simultaneous_clients == Decimal("4")
    assert result.required_clients_for_target_monthly_contribution == Decimal("1000") / Decimal("65")
    assert result.client_value_multiple == Decimal("5")
    assert result.minimum_acceptable_value_multiple == Decimal("3")
