"""Read-only kernel planning values. This lane does not compute formulas."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from evaluation.commerce.experiment_draft_types import EVIDENCE_STATES, LANE_CURRENCY, PLANNING_FIELDS, ExperimentDraftError, text


@dataclass(frozen=True)
class PlanningEconomics:
    currency: str
    break_even_cac: str | None
    target_cac: str | None
    break_even_roas: str | None
    target_roas: str | None
    contribution_before_cac: str | None
    contribution_after_cac: str | None
    target_contribution: str | None
    client_value_or_internal_profitability_effect: str | None
    evidence_state: str
    assumed_at: str
    assumptions: tuple[str, ...]
    exchange_rate_metadata: Mapping[str, str]
    kernel_authority: str = "backend.economics.kernel"
    formulas_recalculated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "break_even_cac": self.break_even_cac,
            "target_cac": self.target_cac,
            "break_even_roas": self.break_even_roas,
            "target_roas": self.target_roas,
            "contribution_before_cac": self.contribution_before_cac,
            "contribution_after_cac": self.contribution_after_cac,
            "target_contribution": self.target_contribution,
            "client_value_or_internal_profitability_effect": self.client_value_or_internal_profitability_effect,
            "evidence_state": self.evidence_state,
            "assumed_at": self.assumed_at,
            "assumptions": list(self.assumptions),
            "exchange_rate_metadata": dict(self.exchange_rate_metadata),
            "kernel_authority": self.kernel_authority,
            "formulas_recalculated": False,
        }


def money_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if raw.startswith("-"):
        raise ExperimentDraftError("negative_downside_contribution")
    return raw


def planning_from(raw: Mapping[str, Any], lane: str) -> PlanningEconomics:
    currency = text(raw.get("currency") or LANE_CURRENCY.get(lane, "")).upper()
    if currency and LANE_CURRENCY.get(lane) and currency != LANE_CURRENCY[lane]:
        raise ExperimentDraftError("mixed_currency")
    extra = raw.get("exchange_rate_metadata") or {}
    if isinstance(extra, Mapping) and extra.get("convert_to") and extra.get("convert_to") != currency:
        raise ExperimentDraftError("mixed_currency")
    state = text(raw.get("evidence_state") or "assumed")
    if state not in EVIDENCE_STATES:
        state = "unknown"
    values = {name: money_text(raw.get(name)) for name in PLANNING_FIELDS}
    if values["contribution_after_cac"] is not None:
        try:
            if float(values["contribution_after_cac"]) < 0:
                raise ExperimentDraftError("negative_downside_contribution")
        except ValueError as exc:
            raise ExperimentDraftError("malformed_planning_value") from exc
    return PlanningEconomics(
        currency=currency or LANE_CURRENCY.get(lane, "USD"),
        break_even_cac=values["break_even_cac"],
        target_cac=values["target_cac"],
        break_even_roas=values["break_even_roas"],
        target_roas=values["target_roas"],
        contribution_before_cac=values["contribution_before_cac"],
        contribution_after_cac=values["contribution_after_cac"],
        target_contribution=values["target_contribution"],
        client_value_or_internal_profitability_effect=values["client_value_or_internal_profitability_effect"],
        evidence_state=state,
        assumed_at=text(raw.get("assumed_at") or "offline-deterministic"),
        assumptions=tuple(text(item) for item in (raw.get("assumptions") or ()) if text(item)),
        exchange_rate_metadata={str(k): str(v) for k, v in dict(extra).items()} if isinstance(extra, Mapping) else {},
        formulas_recalculated=False,
    )
