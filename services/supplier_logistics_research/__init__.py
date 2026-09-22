"""services.supplier_logistics_research -- product-agnostic supplier and
logistics evidence service for consulting reports.

Composes backend.economics.kernel (Money/EvidenceRef/MarketLane/
calculate_unit_economics), evaluation.commerce.canonical
(SupplierOfferIdentity), and this repository's existing evidence-quality
and risk-severity vocabularies. Does not duplicate the supplier
feasibility scorer or a logistics authority, and never contacts a live
provider, supplier, or payment/shipping system.
"""
from .controls import NegativeControlError, is_verified
from .report import build_supplier_logistics_report
from .schemas import (
    SCHEMA,
    CandidateBoundSupplierIdentity,
    CustomsDutyTaxProfile,
    FieldEvidence,
    GoodsLogisticsProfile,
    LandedCostScenario,
    LeadTimeWindow,
    MoqAvailability,
    NextAction,
    ReturnsDefectAssumptions,
    RiskMatrixEntry,
    ServiceCapacityProfile,
    ShippingCostProfile,
    SupplierLogisticsOffer,
    SupplierLogisticsReport,
)

__all__ = [
    "SCHEMA",
    "NegativeControlError",
    "is_verified",
    "build_supplier_logistics_report",
    "CandidateBoundSupplierIdentity",
    "CustomsDutyTaxProfile",
    "FieldEvidence",
    "GoodsLogisticsProfile",
    "LandedCostScenario",
    "LeadTimeWindow",
    "MoqAvailability",
    "NextAction",
    "ReturnsDefectAssumptions",
    "RiskMatrixEntry",
    "ServiceCapacityProfile",
    "ShippingCostProfile",
    "SupplierLogisticsOffer",
    "SupplierLogisticsReport",
]
