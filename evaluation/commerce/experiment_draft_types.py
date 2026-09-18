"""Types and constants for MarketOS.ExperimentDraft.v1."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

SCHEMA = "MarketOS.ExperimentDraft.v1"
STATES = frozenset({
    "proposed", "evidence_incomplete", "draft_ready", "human_review",
    "approved_for_simulation", "simulated", "paused", "rejected", "completed", "unavailable",
})
LIVE_STATES = frozenset({"campaign_published", "spend_executed", "ads_live", "order_placed"})
CHANNELS = frozenset({"paid_social", "content", "marketplace", "affiliate", "referral", "cro", "email_draft", "organic_social_draft"})
BUSINESS_MODELS = frozenset({"retail_margin", "affiliate", "referral", "commission", "lead_generation", "service"})
MARKET_LANES = frozenset({"MX-MXN", "US-USD", "CA-CAD", "EU-EUR", "UK-GBP"})
LANE_CURRENCY = {"MX-MXN": "MXN", "US-USD": "USD", "CA-CAD": "CAD", "EU-EUR": "EUR", "UK-GBP": "GBP"}
EVIDENCE_STATES = frozenset({"unknown", "missing", "assumed", "derived", "fixture", "simulated", "observed", "stale", "rejected", "malformed"})
FIXTURE_STATES = frozenset({"fixture", "simulated", "assumed", "unknown"})
APPROVAL_STATES = frozenset({"not_requested", "pending", "approved_for_simulation", "rejected", "revoked", "blocked"})
PLANNING_FIELDS = (
    "break_even_cac", "target_cac", "break_even_roas", "target_roas",
    "contribution_before_cac", "contribution_after_cac", "target_contribution",
    "client_value_or_internal_profitability_effect",
)
SECRET_KEY = re.compile(r"(api[_-]?key|authorization|cookie|password|private[_-]?key|secret|token)", re.I)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_(?:live|test)_|gh[pousr]_?|-----BEGIN)", re.I)
HTML_MARK = re.compile(r"<\s*(script|iframe|html|body|img)\b", re.I)
MEDICAL_CLAIM = re.compile(r"\b(cures?|treats?|diagnos(?:e|is)|prevents? disease|fda.?approved|clinically proven to heal)\b", re.I)


class ExperimentDraftError(ValueError):
    """Stable validation error for the draft contract."""


def text(value: Any, limit: int = 280) -> str:
    return " ".join(str(value or "").split())[:limit]


def secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SECRET_KEY.search(str(k)) or secret(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(secret(item) for item in value)
    return bool(SECRET_VALUE.search(str(value))) if value is not None else False


def replay_hash(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
