"""Compatibility adapter for the canonical Decimal economics kernel."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal

from backend.economics.kernel import EconomicsError, Money, UnitEconomicsAssumptions
from backend.economics.kernel import calculate_unit_economics as calculate_canonical_unit_economics
from .contracts import ProductCandidate, SupplierOffer
from .quality import quality_reasons

@dataclass(frozen=True)
class UnitEconomics:
    currency: str
    revenue: float
    landed_cost: float
    payment_fee: float
    contribution_before_ads: float
    break_even_roas: float | None
    max_cac: float
    margin_rate: float | None
    eligible: bool
    reasons: tuple[str, ...]
    def to_dict(self) -> dict:
        return {"currency": self.currency, "revenue": self.revenue, "landed_cost": self.landed_cost, "payment_fee": self.payment_fee, "contribution_before_ads": self.contribution_before_ads, "break_even_roas": self.break_even_roas, "max_cac": self.max_cac, "margin_rate": self.margin_rate, "eligible": self.eligible, "reasons": list(self.reasons)}

def calculate_unit_economics(
    product: ProductCandidate,
    offer: SupplierOffer | None,
    *,
    payment_fee_rate: float = 0.029,
    payment_fee_fixed: float = 0.30,
    refund_rate: float = 0.0,
) -> UnitEconomics:
    """Preserve the historical float report while delegating its math."""
    reasons: list[str] = []
    try:
        selling_price = max(Decimal(str(product.selling_price)), Decimal("0"))
        refund = min(Decimal("1"), max(Decimal(str(refund_rate)), Decimal("0")))
    except (TypeError, ValueError):
        return UnitEconomics(product.currency, 0.0, 0.0, 0.0, 0.0, None, 0.0, None, False, ("invalid_selling_price",))
    revenue = float((selling_price * (Decimal("1") - refund)).quantize(Decimal("0.0001")))
    if offer is None:
        return UnitEconomics(product.currency, revenue, 0.0, 0.0, 0.0, None, 0.0, None, False, ("missing_supplier_offer",))
    if product.currency.upper() != offer.currency.upper():
        return UnitEconomics(product.currency, revenue, 0.0, 0.0, 0.0, None, 0.0, None, False, ("currency_mismatch",))
    try:
        unit_cost = Decimal(str(offer.unit_cost))
        shipping_cost = Decimal(str(offer.shipping_cost))
    except (TypeError, ValueError):
        return UnitEconomics(product.currency, revenue, 0.0, 0.0, 0.0, None, 0.0, None, False, ("invalid_supplier_cost",))
    if unit_cost < 0 or shipping_cost < 0:
        reasons.append("invalid_supplier_cost")
    reasons.extend(quality_reasons(offer.quality))
    try:
        canonical = calculate_canonical_unit_economics(
            Money(selling_price * (Decimal("1") - refund), product.currency, source="legacy_adapter", provenance="legacy_adapter"),
            Money(max(unit_cost, Decimal("0")), product.currency, source="legacy_adapter", provenance="legacy_adapter"),
            assumptions=UnitEconomicsAssumptions(
                supplier_shipping=Money(max(shipping_cost, Decimal("0")), product.currency, source="legacy_adapter", provenance="legacy_adapter"),
                payment_fee_rate=max(Decimal(str(payment_fee_rate)), Decimal("0")),
                payment_fee_fixed=Money(max(Decimal(str(payment_fee_fixed)), Decimal("0")), product.currency, source="legacy_adapter", provenance="legacy_adapter"),
                platform_fee_rate=Decimal("0"),
                return_rate=Decimal("0"),
            ),
        )
    except (EconomicsError, TypeError, ValueError):
        reasons.append("invalid_supplier_cost")
        return UnitEconomics(product.currency, revenue, 0.0, 0.0, 0.0, None, 0.0, None, False, tuple(sorted(set(reasons))))
    landed = float(canonical.product_cost.amount + canonical.supplier_shipping.amount)
    fee = float(canonical.payment_fees.amount)
    contribution = float(canonical.contribution_before_cac.amount)
    if contribution <= 0:
        reasons.append("negative_contribution_margin")
    if revenue <= 0:
        reasons.append("missing_selling_price")
    if offer.inventory_units is not None and offer.inventory_units <= 0:
        reasons.append("out_of_stock")
    reasons = sorted(set(reasons))
    break_even = float(canonical.break_even_roas) if canonical.break_even_roas is not None else None
    margin = float(canonical.contribution_margin) if canonical.contribution_margin is not None else None
    return UnitEconomics(product.currency, revenue, round(landed, 4), round(fee, 4), round(contribution, 4), break_even, round(contribution, 4), margin, not reasons, tuple(reasons))
