"""backend.commerce — canonical commerce loop primitives.

This package provides the complementary commerce truth layer:
signal normalization, product ranking, creative generation,
launch orchestration, and metrics feedback reconciliation.
"""
from .contracts import (
    CampaignOutcome,
    CommerceCycleReport,
    CommerceSignal,
    CreativeBundle,
    LaunchPlan,
    RankedOpportunity,
)
from .creative import CreativeComposer
from .feedback import FeedbackRecorder
from .launch import LaunchExecutor
from .loop import CommerceLoop, run_commerce_cycle
from .scoring import OpportunityScorer

__all__ = [
    "CampaignOutcome",
    "CommerceCycleReport",
    "CommerceSignal",
    "CreativeBundle",
    "LaunchPlan",
    "RankedOpportunity",
    "CreativeComposer",
    "FeedbackRecorder",
    "LaunchExecutor",
    "CommerceLoop",
    "run_commerce_cycle",
    "OpportunityScorer",
]
