from __future__ import annotations

from typing import Any, Mapping

def evaluate_owner_portfolio_gate(
    synthesis_report: Mapping[str, Any] | None
) -> dict[str, Any]:
    """
    Evaluates whether the owner portfolio meets the threshold for
    downstream brand/page research (>= 3 distinct, active product candidates).

    This is an offline planning gate. It does not trigger any live actions,
    branding generation, or spend.

    Args:
        synthesis_report: The ProductOpportunitySynthesisReport dictionary.

    Returns:
        dict with status (ready/not_ready), reasons, and eligible_candidate_ids.
    """
    if not synthesis_report:
        return {
            "status": "not_ready",
            "reasons": ["missing_synthesis_report"],
            "eligible_candidate_ids": []
        }

    candidates = synthesis_report.get("candidates", [])

    active_distinct_ids = set()

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue

        candidate_id = candidate.get("candidate_id")

        # Identity must be present and valid
        if not candidate_id or not isinstance(candidate_id, str) or not candidate_id.strip():
            continue

        # Exclude archived
        if candidate.get("status") == "archived":
            continue

        active_distinct_ids.add(candidate_id.strip())

    # Sort for deterministic output
    eligible_candidate_ids = sorted(list(active_distinct_ids))

    if len(eligible_candidate_ids) >= 3:
        return {
            "status": "ready",
            "reasons": [],
            "eligible_candidate_ids": eligible_candidate_ids
        }
    else:
        return {
            "status": "not_ready",
            "reasons": [f"insufficient_active_candidates: {len(eligible_candidate_ids)} found, 3 required"],
            "eligible_candidate_ids": eligible_candidate_ids
        }
