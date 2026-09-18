"""Fixture promotion guard. Planning formulas stay in the kernel."""
from typing import Any, Mapping

from evaluation.commerce.experiment_draft_economics import PlanningEconomics
from evaluation.commerce.experiment_draft_types import FIXTURE_STATES


def fixture_promoted(planning: PlanningEconomics, raw: Mapping[str, Any]) -> bool:
    return planning.evidence_state in FIXTURE_STATES and bool(raw.get("promote_evidence_to_live"))
