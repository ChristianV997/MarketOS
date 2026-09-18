"""The five named dry-run lifecycle scenarios from the integration spec.

Each builder returns a fully-formed ``DryRunScenarioInput`` with concrete
(not placeholder-zero) economics, so ``run_dry_run_lifecycle`` exercises the
real kernel math, the real promotion gate logic, and produces a distinct,
deterministic ``achievable_stage`` per scenario:

  1. hydroponics_positive_candidate       -> full evidence, all gates clear, reaches scale_candidate.
  2. smart_pet_support_burden_candidate   -> good economics, unassigned support ownership blocks at launch_draft.
  3. solar_4g_security_blocked_candidate  -> missing compliance/SIM/support evidence blocks earlier, at supplier_validated.
  4. commodity_electronics_rejected_candidate -> thin margin + oversaturated competition blocks at economics_screened.
  5. high_ticket_deferred_candidate       -> good economics but missing reverse-logistics/warranty evidence blocks at launch_draft.

All money values are explicit ``Decimal``-backed ``Money`` with an
``evidence_state`` tag; no scenario invents a live provider result.
"""
from __future__ import annotations

from decimal import Decimal

from backend.economics.kernel import EvidenceRef, MarketLane, Money, UnitEconomicsAssumptions

from .canonical import BusinessModel, CommercialOwnership, CompetitionSnapshot, OwnershipAssignment
from .dry_run_lifecycle import DryRunScenarioInput

_ALL_GATES_TRUE = {
    "exact_sku": True, "destination_lane": True, "shipping": True, "return_route": True,
    "warranty_route": True, "support_owner": True, "supplier_permission": True,
    "compliance": True, "economics": True, "competition": True, "customer_facing_promise": True,
}


def _known_ownership(method: str = "retail_margin") -> CommercialOwnership:
    return CommercialOwnership(
        merchant_of_record=OwnershipAssignment("merchant_of_record", "MarketOS Operator LLC"),
        fulfillment_owner=OwnershipAssignment("fulfillment_owner", "Supplier-managed 3PL"),
        warranty_owner=OwnershipAssignment("warranty_owner", "Supplier"),
        return_owner=OwnershipAssignment("return_owner", "MarketOS Operator LLC"),
        support_owner=OwnershipAssignment("support_owner", "MarketOS Operator LLC"),
        payment_collection_owner=OwnershipAssignment("payment_collection_owner", "MarketOS Operator LLC"),
        commission_or_margin_method=method,
    )


def hydroponics_positive_candidate() -> DryRunScenarioInput:
    """Scenario 1: clean evidence, healthy margin, low competition — should clear every gate."""
    evidence = EvidenceRef("ev-hydro-1", source_type="cj_readonly_fixture", evidence_state="observed", human_confirmed=True)
    lane = MarketLane(
        lane_id="us-domestic-hydro", origin="US", ship_from="US", warehouse="US-WEST",
        destination_country="US", currency="USD", tax_rate=Decimal("0.07"), duty_rate=Decimal("0"),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("3.50", "USD", evidence_state="observed"),
        payment_fee_rate=Decimal("0.029"), payment_fee_fixed=Money("0.30", "USD"),
        return_rate=Decimal("0.06"), defect_rate=Decimal("0.01"), warranty_rate=Decimal("0.0"),
        support_reserve_rate=Decimal("0.01"), chargeback_rate=Decimal("0.005"),
        fx_reserve_rate=Decimal("0"), discount_rate=Decimal("0"), marketplace_fee_rate=Decimal("0"),
        affiliate_fee_rate=Decimal("0"), cac=Money("6.00", "USD", evidence_state="observed"),
        evidence_refs=(evidence,),
    )
    competition = CompetitionSnapshot(
        candidate_id="hydroponics-nutrient-kit", lane_id=lane.lane_id, observed_offer_count=14,
        price_band_min=34.99, price_band_max=59.99, saturation_score=0.28,
        dominant_retailer="", dominant_retailer_share=0.18, evidence_ref=evidence,
    )
    return DryRunScenarioInput(
        scenario_id="hydroponics_positive_candidate",
        candidate_id="hydroponics-nutrient-kit",
        business_model=BusinessModel.RETAIL_MARGIN,
        price=Money("44.99", "USD", evidence_state="observed"),
        product_cost=Money("11.20", "USD", evidence_state="observed"),
        lane=lane,
        assumptions=assumptions,
        ownership=_known_ownership(),
        competition=competition,
        gate_satisfaction=dict(_ALL_GATES_TRUE),
        evidence_state="observed",
    )


def smart_pet_support_burden_candidate() -> DryRunScenarioInput:
    """Scenario 2: fine economics, but no accountable support owner (high support-ticket item)."""
    evidence = EvidenceRef("ev-pet-1", source_type="alibaba_supplier_snapshot", evidence_state="observed")
    lane = MarketLane(
        lane_id="us-domestic-petfeeder", origin="CN", ship_from="US", warehouse="US-CENTRAL",
        destination_country="US", currency="USD", tax_rate=Decimal("0.07"), duty_rate=Decimal("0.02"),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("5.00", "USD", evidence_state="observed"),
        payment_fee_rate=Decimal("0.029"), payment_fee_fixed=Money("0.30", "USD"),
        return_rate=Decimal("0.14"), defect_rate=Decimal("0.05"), warranty_rate=Decimal("0.03"),
        support_reserve_rate=Decimal("0.06"), chargeback_rate=Decimal("0.01"),
        fx_reserve_rate=Decimal("0"), discount_rate=Decimal("0"), marketplace_fee_rate=Decimal("0"),
        affiliate_fee_rate=Decimal("0"), cac=Money("14.00", "USD", evidence_state="observed"),
        evidence_refs=(evidence,),
    )
    competition = CompetitionSnapshot(
        candidate_id="smart-pet-feeder", lane_id=lane.lane_id, observed_offer_count=22,
        price_band_min=59.0, price_band_max=129.0, saturation_score=0.45,
        dominant_retailer="", dominant_retailer_share=0.22, evidence_ref=evidence,
    )
    ownership = CommercialOwnership(
        merchant_of_record=OwnershipAssignment("merchant_of_record", "MarketOS Operator LLC"),
        fulfillment_owner=OwnershipAssignment("fulfillment_owner", "Supplier-managed 3PL"),
        warranty_owner=OwnershipAssignment("warranty_owner", "Supplier"),
        return_owner=OwnershipAssignment("return_owner", "MarketOS Operator LLC"),
        support_owner=OwnershipAssignment("support_owner"),  # unknown: high app-connectivity ticket volume, no owner assigned
        payment_collection_owner=OwnershipAssignment("payment_collection_owner", "MarketOS Operator LLC"),
        commission_or_margin_method="retail_margin",
    )
    gates = dict(_ALL_GATES_TRUE)
    gates["support_owner"] = False
    return DryRunScenarioInput(
        scenario_id="smart_pet_support_burden_candidate",
        candidate_id="smart-pet-feeder",
        business_model=BusinessModel.RETAIL_MARGIN,
        price=Money("79.99", "USD", evidence_state="observed"),
        product_cost=Money("24.50", "USD", evidence_state="observed"),
        lane=lane,
        assumptions=assumptions,
        ownership=ownership,
        competition=competition,
        gate_satisfaction=gates,
        evidence_state="observed",
    )


def solar_4g_security_blocked_candidate() -> DryRunScenarioInput:
    """Scenario 3: SIM/regulatory compliance and support evidence are both missing."""
    evidence = EvidenceRef("ev-solar-1", source_type="manual_csv_import", evidence_state="fixture")
    lane = MarketLane(
        lane_id="us-domestic-solarcam", origin="CN", ship_from="US", warehouse="US-EAST",
        destination_country="US", currency="USD", tax_rate=Decimal("0.07"), duty_rate=Decimal("0.03"),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("9.00", "USD", evidence_state="assumed"),
        payment_fee_rate=Decimal("0.029"), payment_fee_fixed=Money("0.30", "USD"),
        return_rate=Decimal("0.10"), defect_rate=Decimal("0.04"), warranty_rate=Decimal("0.02"),
        support_reserve_rate=Decimal("0.05"), chargeback_rate=Decimal("0.01"),
        fx_reserve_rate=Decimal("0"), discount_rate=Decimal("0"), marketplace_fee_rate=Decimal("0"),
        affiliate_fee_rate=Decimal("0"), cac=Money("22.00", "USD", evidence_state="assumed"),
        evidence_refs=(evidence,),
    )
    competition = CompetitionSnapshot(
        candidate_id="solar-4g-security-camera", lane_id=lane.lane_id, observed_offer_count=9,
        price_band_min=119.0, price_band_max=249.0, saturation_score=0.4,
        dominant_retailer="", dominant_retailer_share=0.3, evidence_ref=evidence,
    )
    ownership = CommercialOwnership(
        merchant_of_record=OwnershipAssignment("merchant_of_record", "MarketOS Operator LLC"),
        fulfillment_owner=OwnershipAssignment("fulfillment_owner", "Supplier-managed 3PL"),
        warranty_owner=OwnershipAssignment("warranty_owner", "Supplier"),
        return_owner=OwnershipAssignment("return_owner", "MarketOS Operator LLC"),
        support_owner=OwnershipAssignment("support_owner"),  # unknown: cellular-carrier support not staffed
        payment_collection_owner=OwnershipAssignment("payment_collection_owner", "MarketOS Operator LLC"),
        commission_or_margin_method="retail_margin",
    )
    gates = dict(_ALL_GATES_TRUE)
    gates["compliance"] = False  # FCC/cellular-carrier SIM certification evidence not on file
    gates["support_owner"] = False
    return DryRunScenarioInput(
        scenario_id="solar_4g_security_blocked_candidate",
        candidate_id="solar-4g-security-camera",
        business_model=BusinessModel.RETAIL_MARGIN,
        price=Money("179.00", "USD", evidence_state="assumed"),
        product_cost=Money("62.00", "USD", evidence_state="assumed"),
        lane=lane,
        assumptions=assumptions,
        ownership=ownership,
        competition=competition,
        gate_satisfaction=gates,
        evidence_state="fixture",
    )


def commodity_electronics_rejected_candidate() -> DryRunScenarioInput:
    """Scenario 4: thin/negative margin in an oversaturated, retailer-dominated lane."""
    evidence = EvidenceRef("ev-usbc-1", source_type="aliexpress_supplier_snapshot", evidence_state="observed")
    lane = MarketLane(
        lane_id="us-domestic-usbc-cable", origin="CN", ship_from="US", warehouse="US-WEST",
        destination_country="US", currency="USD", tax_rate=Decimal("0.07"), duty_rate=Decimal("0"),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("1.20", "USD", evidence_state="observed"),
        payment_fee_rate=Decimal("0.029"), payment_fee_fixed=Money("0.30", "USD"),
        return_rate=Decimal("0.09"), defect_rate=Decimal("0.03"), warranty_rate=Decimal("0"),
        support_reserve_rate=Decimal("0.01"), chargeback_rate=Decimal("0.01"),
        fx_reserve_rate=Decimal("0"), discount_rate=Decimal("0"), marketplace_fee_rate=Decimal("0.08"),
        affiliate_fee_rate=Decimal("0"), cac=Money("5.50", "USD", evidence_state="observed"),
        evidence_refs=(evidence,),
    )
    competition = CompetitionSnapshot(
        candidate_id="usb-c-cable-3pack", lane_id=lane.lane_id, observed_offer_count=340,
        price_band_min=6.99, price_band_max=12.99, saturation_score=0.91,
        dominant_retailer="Anker (via Amazon)", dominant_retailer_share=0.62, evidence_ref=evidence,
    )
    gates = dict(_ALL_GATES_TRUE)
    gates["economics"] = False  # margin does not clear the contribution-before-CAC floor
    gates["competition"] = False  # oversaturated, single-retailer-dominated lane
    return DryRunScenarioInput(
        scenario_id="commodity_electronics_rejected_candidate",
        candidate_id="usb-c-cable-3pack",
        business_model=BusinessModel.RETAIL_MARGIN,
        price=Money("9.99", "USD", evidence_state="observed"),
        product_cost=Money("8.10", "USD", evidence_state="observed"),
        lane=lane,
        assumptions=assumptions,
        ownership=_known_ownership(),
        competition=competition,
        gate_satisfaction=gates,
        evidence_state="observed",
    )


def high_ticket_deferred_candidate() -> DryRunScenarioInput:
    """Scenario 5: healthy margin, but reverse-logistics and warranty evidence are missing."""
    evidence = EvidenceRef("ev-highticket-1", source_type="alibaba_supplier_snapshot", evidence_state="observed")
    lane = MarketLane(
        lane_id="us-domestic-egraded-bike", origin="CN", ship_from="US", warehouse="US-SOUTH",
        destination_country="US", currency="USD", tax_rate=Decimal("0.07"), duty_rate=Decimal("0.02"),
    )
    assumptions = UnitEconomicsAssumptions(
        supplier_shipping=Money("85.00", "USD", evidence_state="observed"),
        payment_fee_rate=Decimal("0.029"), payment_fee_fixed=Money("0.30", "USD"),
        return_rate=Decimal("0.05"), defect_rate=Decimal("0.02"), warranty_rate=Decimal("0.04"),
        support_reserve_rate=Decimal("0.02"), chargeback_rate=Decimal("0.005"),
        fx_reserve_rate=Decimal("0"), discount_rate=Decimal("0"), marketplace_fee_rate=Decimal("0"),
        affiliate_fee_rate=Decimal("0"), cac=Money("95.00", "USD", evidence_state="observed"),
        evidence_refs=(evidence,),
    )
    competition = CompetitionSnapshot(
        candidate_id="e-cargo-bike", lane_id=lane.lane_id, observed_offer_count=11,
        price_band_min=1499.0, price_band_max=2799.0, saturation_score=0.33,
        dominant_retailer="", dominant_retailer_share=0.2, evidence_ref=evidence,
    )
    ownership = CommercialOwnership(
        merchant_of_record=OwnershipAssignment("merchant_of_record", "MarketOS Operator LLC"),
        fulfillment_owner=OwnershipAssignment("fulfillment_owner", "Freight-forwarder 3PL"),
        warranty_owner=OwnershipAssignment("warranty_owner"),  # unknown: no warranty-claim process confirmed with supplier
        return_owner=OwnershipAssignment("return_owner"),  # unknown: reverse-logistics route for oversized freight not confirmed
        support_owner=OwnershipAssignment("support_owner", "MarketOS Operator LLC"),
        payment_collection_owner=OwnershipAssignment("payment_collection_owner", "MarketOS Operator LLC"),
        commission_or_margin_method="retail_margin",
    )
    gates = dict(_ALL_GATES_TRUE)
    gates["return_route"] = False  # oversized-freight reverse-logistics route not confirmed
    gates["warranty_route"] = False  # supplier warranty-claim process not confirmed
    return DryRunScenarioInput(
        scenario_id="high_ticket_deferred_candidate",
        candidate_id="e-cargo-bike",
        business_model=BusinessModel.RETAIL_MARGIN,
        price=Money("2199.00", "USD", evidence_state="observed"),
        product_cost=Money("980.00", "USD", evidence_state="observed"),
        lane=lane,
        assumptions=assumptions,
        ownership=ownership,
        competition=competition,
        gate_satisfaction=gates,
        evidence_state="observed",
    )


SCENARIO_BUILDERS = (
    hydroponics_positive_candidate,
    smart_pet_support_burden_candidate,
    solar_4g_security_blocked_candidate,
    commodity_electronics_rejected_candidate,
    high_ticket_deferred_candidate,
)


__all__ = [
    "hydroponics_positive_candidate",
    "smart_pet_support_burden_candidate",
    "solar_4g_security_blocked_candidate",
    "commodity_electronics_rejected_candidate",
    "high_ticket_deferred_candidate",
    "SCENARIO_BUILDERS",
]
