"""services.ecommerce_operator.scale_decision — make_kill_scale_decision.

Combines contribution profit (not just ROAS) with the existing kill-signal
primitive (agents.auto_kill.should_kill) and the real spend risk gate
(backend.risk.gate.check_spend, read-only here — never calls record_spend,
since this module only evaluates scale feasibility, it doesn't execute a
live scale-up). Decision values match the task spec exactly: kill,
iterate_offer, iterate_creative, continue_test, scale_cautiously,
scale_approved, blocked.
"""
from __future__ import annotations

import logging
import os

from backend.experiments.audit_log import log_transition
from backend.experiments.envelope import CommercialRunEnvelope

from .schemas import ContributionProfitResult, ScaleDecision

_log = logging.getLogger(__name__)

# Minimum order count before a scale/kill call trusts contribution-margin/
# ROAS signal over "keep testing" — mirrors core/content/patterns.py's
# PatternStore min_samples=20 A/B-validity convention.
_MIN_EVIDENCE_ORDERS = int(os.getenv("ECOMMERCE_MIN_EVIDENCE_ORDERS", "20"))


def make_kill_scale_decision(
    envelope: CommercialRunEnvelope,
    contribution: ContributionProfitResult,
    *,
    roas: float,
    proposed_scale_amount: float = 0.0,
) -> ScaleDecision:
    """Never raises."""
    kill_criteria = (envelope.inputs or {}).get("kill_criteria") or {}
    min_roas = kill_criteria.get("min_roas", 1.0)
    min_contribution_margin = kill_criteria.get("min_contribution_margin", 0.0)
    max_spend_before_kill = kill_criteria.get("max_spend_before_kill", 0.0)

    raw_kill_signal = False
    try:
        from agents.auto_kill import should_kill
        raw_kill_signal = should_kill({"spend": contribution.actual_spend, "roas": roas})
    except Exception as exc:  # noqa: BLE001
        _log.debug("scale_decision_auto_kill_check_failed error=%s", exc)

    if envelope.status == "blocked":
        decision, reason, next_action = "blocked", (
            "; ".join(envelope.blocked_reasons) or "launch readiness not met"
        ), "resolve blocked_reasons and re-evaluate launch readiness"

    elif (
        raw_kill_signal
        or contribution.contribution_profit < 0
        or (max_spend_before_kill and contribution.actual_spend >= max_spend_before_kill and roas < min_roas)
    ):
        decision, next_action = "kill", "pause spend on this product/offer"
        reason = (
            f"contribution_profit={contribution.contribution_profit:.2f} roas={roas:.2f} "
            f"— below survival threshold at current spend {contribution.actual_spend:.2f}"
        )

    elif contribution.contribution_margin < min_contribution_margin:
        decision, next_action = "iterate_offer", "revisit pricing/supplier/offer, not creative"
        reason = (
            f"contribution_margin {contribution.contribution_margin:.4f} below floor "
            f"{min_contribution_margin} — the unit economics, not the ad, is the constraint"
        )

    elif roas < min_roas:
        decision, next_action = "iterate_creative", "test new hooks/angles before killing"
        reason = f"roas {roas:.2f} below required {min_roas} despite acceptable contribution margin"

    elif contribution.actual_orders < _MIN_EVIDENCE_ORDERS:
        decision, next_action = "continue_test", f"accumulate more orders (target {_MIN_EVIDENCE_ORDERS})"
        reason = f"only {contribution.actual_orders} orders observed — not enough evidence for a scale call"

    else:
        risk_check = {"allowed": True, "adjusted_amount": proposed_scale_amount, "reason": "no_scale_requested"}
        if proposed_scale_amount > 0:
            try:
                from backend.risk.gate import check_spend
                risk_check = check_spend(proposed_scale_amount)
            except Exception as exc:  # noqa: BLE001
                _log.debug("scale_decision_risk_gate_check_failed error=%s", exc)

        if not risk_check["allowed"] or risk_check["adjusted_amount"] < proposed_scale_amount:
            decision, next_action = "scale_cautiously", (
                f"scale to {risk_check['adjusted_amount']:.2f} instead of {proposed_scale_amount:.2f}"
            )
            reason = f"risk gate capped scale-up: {risk_check['reason']}"
        else:
            decision, next_action = "scale_approved", f"scale spend to {proposed_scale_amount:.2f}"
            reason = (
                f"contribution_margin {contribution.contribution_margin:.4f} and roas {roas:.2f} "
                f"both clear thresholds with {contribution.actual_orders} orders of evidence"
            )

    result = ScaleDecision(
        decision=decision,
        decision_reason=reason,
        next_action=next_action,
        contribution_profit=contribution.contribution_profit,
        contribution_margin=contribution.contribution_margin,
        roas=roas,
    )

    envelope.outputs["scale_decision"] = result.to_dict()
    log_transition(envelope, "scale_decision_made", data=result.to_dict())

    return result
