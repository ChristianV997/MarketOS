"""services.geographic_opportunity -- offline, manual-first geographic
opportunity and trade-feasibility evidence service.

Composes backend.economics.kernel (Money/EvidenceRef/MarketLane/
calculate_unit_economics) and this repository's established evidence-
quality vocabulary style. Does not duplicate the supplier feasibility
scorer or any economics authority, and never contacts a live provider
(UN Comtrade included), places an import order, or moves inventory or
payment.
"""
from .controls import (
    FxProvenanceError,
    NegativeControlError,
    UnsupportedRegulatoryInferenceError,
    is_verified,
    reject_unsafe_input,
    reject_unsupported_regulatory_claim,
    require_fx_provenance,
    require_matching_currency,
    require_present,
)
from .export import build_client_safe_export, collect_evidence_notes
from .report import build_geographic_opportunity_report
from .schemas import (
    SCHEMA,
    BilateralTradeFlowObservation,
    CandidateBoundTradeIdentity,
    DestinationPriceObservation,
    DestinationSourceComparison,
    FieldEvidence,
    FreightDutyAssumptions,
    GeographicOpportunityReport,
    LandedCostScenario,
    NextResearchAction,
    OpportunityRiskEntry,
    RegulatoryComplianceObservation,
    ReturnsLeadTimeAssumptions,
    ServiceCapacityByGeography,
    TradeOpportunityOffer,
)

__all__ = [
    "SCHEMA",
    "FxProvenanceError",
    "NegativeControlError",
    "UnsupportedRegulatoryInferenceError",
    "is_verified",
    "reject_unsafe_input",
    "reject_unsupported_regulatory_claim",
    "require_fx_provenance",
    "require_matching_currency",
    "require_present",
    "build_client_safe_export",
    "collect_evidence_notes",
    "build_geographic_opportunity_report",
    "BilateralTradeFlowObservation",
    "CandidateBoundTradeIdentity",
    "DestinationPriceObservation",
    "DestinationSourceComparison",
    "FieldEvidence",
    "FreightDutyAssumptions",
    "GeographicOpportunityReport",
    "LandedCostScenario",
    "NextResearchAction",
    "OpportunityRiskEntry",
    "RegulatoryComplianceObservation",
    "ReturnsLeadTimeAssumptions",
    "ServiceCapacityByGeography",
    "TradeOpportunityOffer",
]
