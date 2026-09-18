"""Pure commerce evaluation primitives for MarketOS."""

from .contracts import CampaignCandidate, CampaignObservation, CreativeCandidate, DataQuality, ProductCandidate, SupplierOffer
from .economics import UnitEconomics, calculate_unit_economics
from .experiments import ExperimentResult, evaluate_experiment
from .quality_certification import (
    CANONICAL_QUALITY_AUTHORITY,
    DeterministicReplayCertifier,
    ExpectationRule,
    ExpectationSuite,
    QualityAssertionResult,
    QualityAssertionState,
    ReplayCertificationReport,
)
from .readiness import LaunchReadiness, evaluate_campaign, evaluate_product

__all__ = [
    "CANONICAL_QUALITY_AUTHORITY",
    "CampaignCandidate",
    "CampaignObservation",
    "CreativeCandidate",
    "DataQuality",
    "DeterministicReplayCertifier",
    "ExpectationRule",
    "ExpectationSuite",
    "ExperimentResult",
    "LaunchReadiness",
    "ProductCandidate",
    "QualityAssertionResult",
    "QualityAssertionState",
    "ReplayCertificationReport",
    "SupplierOffer",
    "UnitEconomics",
    "calculate_unit_economics",
    "evaluate_campaign",
    "evaluate_experiment",
    "evaluate_product",
]
