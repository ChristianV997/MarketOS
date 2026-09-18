"""Pure commerce evaluation primitives for MarketOS."""

from .contracts import CampaignCandidate, CampaignObservation, CreativeCandidate, DataQuality, ProductCandidate, SupplierOffer
from .economics import UnitEconomics, calculate_unit_economics
from .experiments import ExperimentResult, evaluate_experiment
from .quality import (
    CANONICAL_QUALITY_AUTHORITY,
    DeterministicReplayCertifier,
    ExpectationRule,
    ExpectationSuite,
    QualityAssertionResult,
    QualityAssertionState,
    ReplayCertificationReport,
    certify_data_quality,
    deduplicate_observations,
    quality_reasons,
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
    "certify_data_quality",
    "deduplicate_observations",
    "evaluate_campaign",
    "evaluate_experiment",
    "evaluate_product",
    "quality_reasons",
]
