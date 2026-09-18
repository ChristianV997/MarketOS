"""Draft-only experiment contract bridging an offer to a simulated plan.

This is a planning and simulation layer. It never publishes ads, spends
money, mutates campaigns, messages customers, changes storefronts, places
orders, or calls providers.

Existing authorities reused by reference only:
- Governor budgets/caps: evaluation.companyos.resource_execution_governor
- Approval Ledger: evaluation.companyos.approval_ledger
- Launch Draft Pack / Site Draft Builder IDs only
- Financial kernel planning values are carried, never recalculated
- evaluation.experiments remains the observation t-test module

OpenFeature/GrowthBook/OpenLineage/OTEL patterns used as concepts only.
Nothing is vendored.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from evaluation.commerce.experiment_draft_authorities import (
    GOVERNOR_ACTION,
    LEDGER_REQUEST_TYPE,
    authority_bundle,
)

SCHEMA = "MarketOS.ExperimentDraft.v1"
PRODUCER = "evaluation.commerce.experiment_draft"

STATES = frozenset(
    {
        "proposed",
        "evidence_incomplete",
        "draft_ready",
        "human_review",
        "approved_for_simulation",
        "simulated",
        "paused",
        "rejected",
        "completed",
        "unavailable",
    }
)
LIVE_STATES = frozenset({"campaign_published", "spend_executed", "ads_live", "order_placed"})
CHANNELS = frozenset(
    {
        "paid_social",
        "content",
        "marketplace",
        "affiliate",
        "referral",
        "cro",
        "email_draft",
        "organic_social_draft",
    }
)
BUSINESS_MODELS = frozenset(
    {
        "retail_margin",
        "affiliate",
        "referral",
        "commission",
        "lead_generation",
        "service",
    }
)
MARKET_LANES = frozenset({"MX-MXN", "US-USD", "CA-CAD", "EU-EUR", "UK-GBP"})
LANE_CURRENCY = {
    "MX-MXN": "MXN",
    "US-USD": "USD",
    "CA-CAD": "CAD",
    "EU-EUR": "EUR",
    "UK-GBP": "GBP",
}
EVIDENCE_STATES = frozenset(
    {
        "unknown",
        "missing",
        "assumed",
        "derived",
        "fixture",
        "simulated",
        "observed",
        "stale",
        "rejected",
        "malformed",
    }
)
FIXTURE_STATES = frozenset({"fixture", "simulated", "assumed", "unknown"})
APPROVAL_STATES = frozenset(
    {
        "not_requested",
        "pending",
        "approved_for_simulation",
        "rejected",
        "revoked",
        "blocked",
    }
)
PLANNING_FIELDS = (
    "break_even_cac",
    "target_cac",
    "break_even_roas",
    "target_roas",
    "contribution_before_cac",
    "contribution_after_cac",
    "target_contribution",
    "client_value_or_internal_profitability_effect",
)
SECRET_KEY = re.compile(
    r"(api[_-]?key|authorization|cookie|password|private[_-]?key|secret|token)",
    re.I,
)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_(?:live|test)_|gh[pousr]_?|-----BEGIN)", re.I)
HTML_MARK = re.compile(r"<\s*(script|iframe|html|body|img)\b", re.I)
MEDICAL_CLAIM = re.compile(
    r"\b(cures?|treats?|diagnos(?:e|is)|prevents? disease|fda.?approved|clinically proven to heal)\b",
    re.I,
)
_REGISTRY: dict[str, str] = {}


class ExperimentDraftError(ValueError):
    """Stable validation error for the draft contract."""


@dataclass(frozen=True)
class PlanningEconomics:
    """Read-only kernel planning values. This lane does not compute them."""

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
            "formulas_recalculated": self.formulas_recalculated,
        }
