from dataclasses import dataclass
from typing import Mapping

from backend.economics.kernel import EvidenceRef as EvidenceReference

@dataclass(frozen=True)
class ReturnEligibilityDecision:
    eligible: bool
    reason: str
    missing_evidence: tuple[str, ...]

def evaluate_return_eligibility(
    item_category: str,
    days_since_delivery: int,
    condition: str,
    evidence: Mapping[str, EvidenceReference | None],
) -> ReturnEligibilityDecision:
    """
    Deterministically evaluates whether an item is eligible for return.
    Handles explicit missing evidence vs missing criteria gracefully.
    Does not execute external actions.
    """
    missing = []

    # 1. Require purchase receipt
    if evidence.get("receipt") is None:
        missing.append("receipt_missing")

    # 2. Require return shipping label or carrier proof if pre-authorized
    if evidence.get("authorization") is None and days_since_delivery > 30:
        missing.append("authorization_missing_for_late_return")

    if missing:
        return ReturnEligibilityDecision(
            eligible=False,
            reason="missing_required_evidence",
            missing_evidence=tuple(sorted(missing))
        )

    if days_since_delivery < 0:
        return ReturnEligibilityDecision(eligible=False, reason="invalid_delivery_date", missing_evidence=())

    if item_category == "oversized_freight":
        # Needs explicit freight scheduling proof
        if evidence.get("freight_schedule") is None:
            return ReturnEligibilityDecision(
                eligible=False,
                reason="freight_schedule_required",
                missing_evidence=("freight_schedule_missing",)
            )

    if condition == "damaged_by_customer":
        return ReturnEligibilityDecision(eligible=False, reason="customer_damaged", missing_evidence=())

    if days_since_delivery > 30:
        return ReturnEligibilityDecision(eligible=False, reason="outside_return_window", missing_evidence=())

    return ReturnEligibilityDecision(eligible=True, reason="eligible", missing_evidence=())
