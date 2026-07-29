"""Agent Hierarchy — Scaling, Geo, Audience, and Risk agents.

Each agent follows the same interface::

    agent.decide(input_data: dict) -> AgentDecision

where ``AgentDecision`` carries the proposed action and the agent's
internal reasoning metadata.

The RiskAgent has *priority override*: its decision supersedes all others.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from backend.risk.config import (
    BASE_MAX_DRAWDOWN, BASE_MAX_DAILY_SPEND, DEFAULT_INITIAL_CAPITAL,
    risk_adaptive_live, adaptive_max_drawdown, adaptive_max_daily_spend,
)


# ---------------------------------------------------------------------------
# Common decision dataclass
# ---------------------------------------------------------------------------


@dataclass
class AgentDecision:
    """Output produced by any agent in the hierarchy."""
    agent: str
    action: str          # "scale" | "hold" | "pause" | "kill" | "expand" | "test" | "retarget"
    confidence: float    # 0–1
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Scaling Agent
# ---------------------------------------------------------------------------


class ScalingAgent:
    """Decides whether to scale a campaign budget up, hold, or kill it.

    Decision logic is ROAS-threshold-based and feeds into the risk layer.
    """

    def __init__(
        self,
        scale_roas: float = 1.8,
        kill_roas: float = 0.8,
        max_scale_factor: float = 1.5,
    ):
        self.scale_roas = scale_roas
        self.kill_roas = kill_roas
        self.max_scale_factor = max_scale_factor

    def decide(self, input_data: dict[str, Any]) -> AgentDecision:
        """
        Parameters
        ----------
        input_data:
            Must contain ``roas`` (float) and ``current_budget`` (float).
            Optional: ``spend``, ``clicks``.
        """
        roas = float(input_data.get("roas", 0.0))
        budget = float(input_data.get("current_budget", 0.0))

        if roas >= self.scale_roas:
            new_budget = round(min(budget * self.max_scale_factor, budget * 1.6), 2)
            confidence = min(1.0, roas / (self.scale_roas * 2))
            return AgentDecision(
                agent="scaling",
                action="scale",
                confidence=round(confidence, 4),
                reason=f"roas={roas} >= scale_threshold={self.scale_roas}",
                metadata={"new_budget": new_budget, "roas": roas},
            )

        if roas < self.kill_roas:
            return AgentDecision(
                agent="scaling",
                action="kill",
                confidence=0.95,
                reason=f"roas={roas} < kill_threshold={self.kill_roas}",
                metadata={"new_budget": 0.0, "roas": roas},
            )

        return AgentDecision(
            agent="scaling",
            action="hold",
            confidence=0.7,
            reason=f"roas={roas} in learning band [{self.kill_roas}, {self.scale_roas})",
            metadata={"new_budget": budget, "roas": roas},
        )


# ---------------------------------------------------------------------------
# Geo Agent
# ---------------------------------------------------------------------------


class GeoAgent:
    """Decides geo-expansion or contraction based on per-country ROAS."""

    def __init__(
        self,
        expand_roas: float = 2.0,
        pause_roas: float = 0.9,
    ):
        self.expand_roas = expand_roas
        self.pause_roas = pause_roas

    def decide(self, input_data: dict[str, Any]) -> AgentDecision:
        """
        Parameters
        ----------
        input_data:
            Must contain ``country`` (str) and ``roas`` (float).
            Optional: ``spend``.
            Phase 6 adaptive geo-economics (optional; absent means legacy
            raw-ROAS behavior regardless of GEO_ECONOMICS_LIVE):
                ``geo_margin_pct`` (float) — net margin % from
                ``calculate_margin_geo`` for this country/payment mix.
        """
        country = str(input_data.get("country", "unknown"))
        roas = float(input_data.get("roas", 0.0))
        geo_margin_pct = input_data.get("geo_margin_pct")

        geo_economics_live = os.getenv("GEO_ECONOMICS_LIVE", "false").lower() == "true"
        effective_roas = roas
        margin_adjusted_roas = roas
        if geo_margin_pct is not None:
            from backend.validation.margin_calculator import geo_margin_adjusted_roas
            margin_adjusted_roas = geo_margin_adjusted_roas(roas, float(geo_margin_pct))
            if geo_economics_live:
                effective_roas = margin_adjusted_roas

        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("geoagent"), "shadow_geo_economics",
                workflow="geo_agent", step="decide",
                data={
                    "country": country,
                    "raw_roas": roas,
                    "geo_margin_pct": geo_margin_pct,
                    "margin_adjusted_roas": round(margin_adjusted_roas, 4),
                    "live": geo_economics_live,
                },
            )
        except Exception:
            pass  # journaling must never block a geo decision

        if effective_roas >= self.expand_roas:
            return AgentDecision(
                agent="geo",
                action="expand",
                confidence=min(1.0, effective_roas / (self.expand_roas * 1.5)),
                reason=f"{country}: roas={effective_roas} >= expand_threshold={self.expand_roas}",
                metadata={"country": country, "roas": effective_roas},
            )

        if effective_roas < self.pause_roas:
            return AgentDecision(
                agent="geo",
                action="pause",
                confidence=0.9,
                reason=f"{country}: roas={effective_roas} < pause_threshold={self.pause_roas}",
                metadata={"country": country, "roas": effective_roas},
            )

        return AgentDecision(
            agent="geo",
            action="test",
            confidence=0.6,
            reason=f"{country}: roas={effective_roas} in test band",
            metadata={"country": country, "roas": effective_roas},
        )


# ---------------------------------------------------------------------------
# Audience Agent
# ---------------------------------------------------------------------------


class AudienceAgent:
    """Decides audience retargeting or expansion based on CTR / CVR signals."""

    def __init__(
        self,
        min_ctr: float = 0.01,
        min_cvr: float = 0.01,
    ):
        self.min_ctr = min_ctr
        self.min_cvr = min_cvr

    def decide(self, input_data: dict[str, Any]) -> AgentDecision:
        """
        Parameters
        ----------
        input_data:
            Optional ``ctr`` (float), ``cvr`` (float), ``audience_size`` (int).
        """
        ctr = float(input_data.get("ctr", 0.0))
        cvr = float(input_data.get("cvr", 0.0))
        audience_size = int(input_data.get("audience_size", 0))

        if ctr >= self.min_ctr and cvr >= self.min_cvr:
            action = "expand" if audience_size < 100_000 else "hold"
            return AgentDecision(
                agent="audience",
                action=action,
                confidence=min(1.0, (ctr / self.min_ctr + cvr / self.min_cvr) / 2),
                reason=f"ctr={ctr}, cvr={cvr} above thresholds; audience_size={audience_size}",
                metadata={"ctr": ctr, "cvr": cvr, "audience_size": audience_size},
            )

        return AgentDecision(
            agent="audience",
            action="retarget",
            confidence=0.65,
            reason=f"ctr={ctr} or cvr={cvr} below thresholds — switch to retargeting",
            metadata={"ctr": ctr, "cvr": cvr},
        )


# ---------------------------------------------------------------------------
# Risk Agent  (priority override)
# ---------------------------------------------------------------------------


class RiskAgent:
    """Risk Agent with *priority override* over all other agents.

    When the RiskAgent issues a ``kill`` or ``pause`` decision the calling
    code *must* respect it regardless of what other agents returned.
    """

    def __init__(
        self,
        max_drawdown: float = BASE_MAX_DRAWDOWN,
        max_daily_spend: float = BASE_MAX_DAILY_SPEND,
        kill_roas: float = 0.5,
    ):
        self.max_drawdown = max_drawdown
        self.max_daily_spend = max_daily_spend
        self.kill_roas = kill_roas

    def decide(self, input_data: dict[str, Any]) -> AgentDecision:
        """
        Parameters
        ----------
        input_data:
            Required-ish:
                ``current_capital`` (float),
                ``peak_capital`` (float),
                ``today_spend`` (float),
                ``roas`` (float),
                ``kill_switch`` (bool).
            Optional (Phase 5 adaptive risk — absent means legacy static
            thresholds apply regardless of ``RISK_ADAPTIVE_LIVE``):
                ``initial_capital`` (float), ``volatility`` (float),
                ``concentration_frac`` (float, 0-1).
        """
        capital = float(input_data.get("current_capital", 1.0))
        peak = float(input_data.get("peak_capital", capital))
        today_spend = float(input_data.get("today_spend", 0.0))
        roas = float(input_data.get("roas", 1.0))
        kill_switch = bool(input_data.get("kill_switch", False))

        initial_capital = float(input_data.get("initial_capital", DEFAULT_INITIAL_CAPITAL))
        volatility = input_data.get("volatility")
        concentration_frac = float(input_data.get("concentration_frac", 0.0))

        static_max_drawdown = self.max_drawdown
        static_max_daily_spend = self.max_daily_spend
        adaptive_dd = adaptive_max_drawdown(
            concentration_frac, volatility, base_drawdown=self.max_drawdown)
        adaptive_spend = adaptive_max_daily_spend(
            capital, initial_capital, volatility, base_spend=self.max_daily_spend)

        adaptive_live = risk_adaptive_live()
        effective_max_drawdown = adaptive_dd if adaptive_live else static_max_drawdown
        effective_max_daily_spend = adaptive_spend if adaptive_live else static_max_daily_spend

        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("riskagent"), "shadow_adaptive_risk",
                workflow="risk_agent", step="decide",
                data={
                    "static_max_drawdown": round(static_max_drawdown, 4),
                    "adaptive_max_drawdown": round(adaptive_dd, 4),
                    "static_max_daily_spend": round(static_max_daily_spend, 2),
                    "adaptive_max_daily_spend": round(adaptive_spend, 2),
                    "concentration_frac": round(concentration_frac, 4),
                    "volatility": volatility,
                    "live": adaptive_live,
                },
            )
        except Exception:
            pass  # journaling must never block a risk decision

        # Hard kill-switch
        if kill_switch:
            return AgentDecision(
                agent="risk",
                action="kill",
                confidence=1.0,
                reason="kill_switch_activated",
                metadata={"override": True},
            )

        # Drawdown check
        if peak > 0:
            drawdown = (peak - capital) / peak
            if drawdown > effective_max_drawdown:
                return AgentDecision(
                    agent="risk",
                    action="kill",
                    confidence=1.0,
                    reason=f"drawdown={drawdown:.2%} > max_drawdown={effective_max_drawdown:.2%}",
                    metadata={"override": True, "drawdown": drawdown},
                )

        # Daily spend cap
        if today_spend >= effective_max_daily_spend:
            return AgentDecision(
                agent="risk",
                action="pause",
                confidence=1.0,
                reason=f"daily_spend={today_spend:.2f} >= cap={effective_max_daily_spend:.2f}",
                metadata={"override": True, "today_spend": today_spend},
            )

        # ROAS emergency floor
        if roas < self.kill_roas:
            return AgentDecision(
                agent="risk",
                action="kill",
                confidence=0.9,
                reason=f"roas={roas} < emergency_floor={self.kill_roas}",
                metadata={"override": True, "roas": roas},
            )

        return AgentDecision(
            agent="risk",
            action="hold",
            confidence=0.5,
            reason="no_risk_condition_triggered",
            metadata={"override": False},
        )

    @staticmethod
    def is_override(decision: AgentDecision) -> bool:
        """Return True if this risk decision should override all other agents."""
        return decision.action in {"kill", "pause"} and decision.metadata.get("override", False)
