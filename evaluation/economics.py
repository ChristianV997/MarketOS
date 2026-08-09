"""Deterministic unit-economics calculations."""
from __future__ import annotations
from dataclasses import dataclass
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

def calculate_unit_economics(product: ProductCandidate, offer: SupplierOffer | None, *, payment_fee_rate: float = 0.029, payment_fee_fixed: float = 0.30, refund_rate: float = 0.0) -> UnitEconomics:
    reasons: list[str] = []
    revenue = round(max(product.selling_price, 0.0) * (1.0 - max(refund_rate, 0.0)), 4)
    if offer is None:
        return UnitEconomics(product.currency, revenue, 0.0, 0.0, 0.0, None, 0.0, None, False, ("missing_supplier_offer",))
    if offer.unit_cost < 0 or offer.shipping_cost < 0:
        reasons.append("invalid_supplier_cost")
    reasons.extend(quality_reasons(offer.quality))
    landed = round(max(offer.unit_cost, 0.0) + max(offer.shipping_cost, 0.0), 4)
    fee = round(revenue * max(payment_fee_rate, 0.0) + max(payment_fee_fixed, 0.0), 4)
    contribution = round(revenue - landed - fee, 4)
    if contribution <= 0: reasons.append("negative_contribution_margin")
    if revenue <= 0: reasons.append("missing_selling_price")
    if offer.inventory_units is not None and offer.inventory_units <= 0: reasons.append("out_of_stock")
    break_even = round(revenue / contribution, 4) if contribution > 0 else None
    margin = round(contribution / revenue, 4) if revenue > 0 else None
    reasons = sorted(set(reasons))
    return UnitEconomics(product.currency, revenue, landed, fee, contribution, break_even, contribution, margin, not reasons, tuple(reasons))
