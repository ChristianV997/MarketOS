"""agents.arbitration — resolve four independent AgentDecisions into one.

agents/hierarchy.py defines ScalingAgent, GeoAgent, AudienceAgent, and
RiskAgent, each producing an AgentDecision from its own slice of the world.
Nothing in production code combines them: api/routes/agents_risk.py calls
all four and logs each decision to a metrics panel, side by side.
RiskAgent.is_override() exists specifically to prevent that — its docstring
says the calling code "must respect it" — but had zero call sites.

This module is the single sanctioned path from "four opinions" to "one
action": arbitrate(decisions) -> ArbitratedDecision.

Design
------
Two tiers:

  Tier 0 (veto)     — RiskAgent.is_override() true → its action wins
                      unconditionally. Confidence never overrides safety.
  Tier 1 (consensus) — no veto. Decisions are grouped by the *axis* of the
                      campaign lever they act on:

                        budget    — ScalingAgent, RiskAgent (its non-veto
                                     "hold" still counts as a budget-axis
                                     opinion)
                        geo       — GeoAgent (per-country targeting)
                        audience  — AudienceAgent (targeting/creative)

                      Agents on different axes are orthogonal — a geo
                      "expand" and an audience "retarget" are not in
                      conflict and both pass through. Same-axis decisions
                      that disagree are resolved conservatively: a
                      halting action (kill/pause) always beats a
                      non-halting one (scale/expand/hold/test/retarget),
                      because an unwanted kill is far more expensive to
                      quietly miss than an unwanted scale. Only when two
                      same-axis decisions disagree *without* either being
                      a halting action does confidence break the tie.

Budget-axis dominance: if the resolved budget-axis action halts spend
(kill/pause), geo and audience axis decisions are recorded but marked
superseded — there's nothing to expand or retarget on a halted campaign.

Totality: arbitrate() never raises and never returns "no decision." Any
internal error, or a same-axis tie neither side can resolve, produces a
safe "hold" with unresolved_conflict=True rather than an arbitrary pick.
Every ArbitratedDecision carries the full input list and a human-readable
trace so a later "why was this killed" question is always answerable.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agents.hierarchy import AgentDecision, RiskAgent

_log = logging.getLogger(__name__)

# Which lever (axis) each agent's decision acts on. An agent not listed here
# gets its own private axis (its name) — safe-by-default orthogonality for
# any future agent this module doesn't yet know about.
_AXIS_BY_AGENT: dict[str, str] = {
    "risk": "budget",
    "scaling": "budget",
    "geo": "geo",
    "audience": "audience",
}

# Actions that halt or reduce spend — the conservative default winner in any
# same-axis disagreement, and the trigger for budget-axis dominance over
# the geo/audience axes.
_HALT_ACTIONS: frozenset[str] = frozenset({"kill", "pause"})

_CONFIDENCE_TIE_EPSILON = 1e-9


@dataclass
class AxisOutcome:
    """The resolved action for one campaign lever (budget / geo / audience)."""
    axis: str
    action: str
    confidence: float
    winning_agent: str
    reason: str
    contributors: list[str] = field(default_factory=list)
    superseded: bool = False
    superseded_reason: str = ""


@dataclass
class ArbitratedDecision:
    """The single authoritative outcome of arbitrating N AgentDecisions."""
    tier: str                        # "veto" | "consensus" | "fallback"
    primary_action: str              # budget-axis action — gates the campaign
    winning_agents: list[str]
    reason: str
    axis_outcomes: dict[str, AxisOutcome] = field(default_factory=dict)
    considered: list[AgentDecision] = field(default_factory=list)
    unresolved_conflict: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "primary_action": self.primary_action,
            "winning_agents": self.winning_agents,
            "reason": self.reason,
            "unresolved_conflict": self.unresolved_conflict,
            "axis_outcomes": {
                axis: {
                    "action": o.action,
                    "confidence": round(o.confidence, 4),
                    "winning_agent": o.winning_agent,
                    "reason": o.reason,
                    "contributors": o.contributors,
                    "superseded": o.superseded,
                    "superseded_reason": o.superseded_reason,
                }
                for axis, o in self.axis_outcomes.items()
            },
            "considered": [
                {"agent": d.agent, "action": d.action,
                 "confidence": d.confidence, "reason": d.reason}
                for d in self.considered
            ],
        }


def _fallback(considered: list[AgentDecision], reason: str) -> ArbitratedDecision:
    """The one place a genuinely unresolvable input lands — always 'hold'."""
    _log.warning("arbitration_fallback reason=%s", reason)
    return ArbitratedDecision(
        tier="fallback",
        primary_action="hold",
        winning_agents=[],
        reason=reason,
        considered=considered,
        unresolved_conflict=True,
    )


def arbitrate(decisions: list[AgentDecision]) -> ArbitratedDecision:
    """Resolve N agent decisions into exactly one ArbitratedDecision.

    Never raises. Never returns an ambiguous or absent action.
    """
    try:
        return _arbitrate(decisions)
    except Exception as exc:  # arbitration itself must never crash a caller
        _log.exception("arbitration_internal_error")
        return _fallback(decisions if isinstance(decisions, list) else [],
                         f"arbitration_internal_error: {exc}")


def _arbitrate(decisions: list[AgentDecision]) -> ArbitratedDecision:
    if not decisions:
        return _fallback([], "no_decisions_provided")

    valid = [d for d in decisions if isinstance(d, AgentDecision) and d.agent]
    if not valid:
        return _fallback(decisions, "no_valid_decisions")

    # ── Tier 0: veto ─────────────────────────────────────────────────────
    risk_dec = next((d for d in valid if d.agent == "risk"), None)
    if risk_dec is not None and RiskAgent.is_override(risk_dec):
        return ArbitratedDecision(
            tier="veto",
            primary_action=risk_dec.action,
            winning_agents=["risk"],
            reason=f"risk_veto: {risk_dec.reason}",
            axis_outcomes={
                "budget": AxisOutcome(
                    axis="budget", action=risk_dec.action,
                    confidence=risk_dec.confidence, winning_agent="risk",
                    reason=risk_dec.reason, contributors=["risk"]),
            },
            considered=valid,
        )

    # ── Tier 1: consensus, grouped by axis ───────────────────────────────
    by_axis: dict[str, list[AgentDecision]] = {}
    for d in valid:
        axis = _AXIS_BY_AGENT.get(d.agent, d.agent)
        by_axis.setdefault(axis, []).append(d)

    axis_outcomes: dict[str, AxisOutcome] = {}
    unresolved = False
    for axis, group in by_axis.items():
        outcome, ambiguous = _resolve_axis(axis, group)
        axis_outcomes[axis] = outcome
        unresolved = unresolved or ambiguous

    # Budget axis gates everything else: a halt there means there is no
    # live campaign left for geo/audience decisions to act on.
    budget = axis_outcomes.get("budget")
    if budget is not None and budget.action in _HALT_ACTIONS:
        for axis, outcome in axis_outcomes.items():
            if axis == "budget":
                continue
            outcome.superseded = True
            outcome.superseded_reason = (
                f"budget_axis_halted (agent={budget.winning_agent}, "
                f"action={budget.action})")

    primary = budget.action if budget is not None else "hold"
    winning_agents = sorted({o.winning_agent for o in axis_outcomes.values()})
    reason_parts = [f"{axis}:{o.action}({o.winning_agent})"
                    for axis, o in sorted(axis_outcomes.items())]
    reason = "consensus — " + ", ".join(reason_parts)

    return ArbitratedDecision(
        tier="consensus",
        primary_action=primary,
        winning_agents=winning_agents,
        reason=reason,
        axis_outcomes=axis_outcomes,
        considered=valid,
        unresolved_conflict=unresolved,
    )


def _resolve_axis(axis: str, group: list[AgentDecision]
                  ) -> tuple[AxisOutcome, bool]:
    """Resolve one axis's decisions to a single AxisOutcome.

    Returns (outcome, ambiguous) — ambiguous=True only when a genuine
    same-axis tie could not be broken and the outcome fell back to hold.
    """
    contributors = [d.agent for d in group]

    if len(group) == 1:
        d = group[0]
        return AxisOutcome(axis=axis, action=d.action, confidence=d.confidence,
                           winning_agent=d.agent, reason=d.reason,
                           contributors=contributors), False

    # All agents on this axis agree — no conflict to resolve.
    actions = {d.action for d in group}
    if len(actions) == 1:
        best = max(group, key=lambda d: d.confidence)
        return AxisOutcome(
            axis=axis, action=best.action, confidence=best.confidence,
            winning_agent=best.agent,
            reason=f"unanimous ({', '.join(contributors)})",
            contributors=contributors), False

    # Disagreement: a halting action always wins (conservative default —
    # a missed scale is cheap, an unwanted kill missed is not).
    halters = [d for d in group if d.action in _HALT_ACTIONS]
    if halters:
        winner = max(halters, key=lambda d: d.confidence)
        return AxisOutcome(
            axis=axis, action=winner.action, confidence=winner.confidence,
            winning_agent=winner.agent,
            reason=(f"conservative_default: halting action from "
                    f"{winner.agent} beats non-halting peers "
                    f"({', '.join(contributors)})"),
            contributors=contributors), False

    # No halting action on either side — break the tie on confidence.
    ranked = sorted(group, key=lambda d: d.confidence, reverse=True)
    top, runner_up = ranked[0], ranked[1]
    if abs(top.confidence - runner_up.confidence) < _CONFIDENCE_TIE_EPSILON:
        # Truly ambiguous — don't guess, default to hold and flag it.
        return AxisOutcome(
            axis=axis, action="hold", confidence=0.0, winning_agent="none",
            reason=(f"unresolved_tie among {', '.join(contributors)} "
                    f"(confidences equal) — defaulted to hold"),
            contributors=contributors), True

    return AxisOutcome(
        axis=axis, action=top.action, confidence=top.confidence,
        winning_agent=top.agent,
        reason=(f"confidence_tiebreak: {top.agent} "
                f"({top.confidence:.3f}) beat {runner_up.agent} "
                f"({runner_up.confidence:.3f})"),
        contributors=contributors), False


__all__ = ["ArbitratedDecision", "AxisOutcome", "arbitrate"]
