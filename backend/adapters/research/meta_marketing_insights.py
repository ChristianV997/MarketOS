"""Operational gate for Meta Marketing API Insights.

Live GET is not wired. The approved research credential allowlist does not
contain a Meta key, so this module never reads a token and never calls Graph.
A supplied fixture is not substituted when an operational read is blocked.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from backend.research.credentials import RESEARCH_CREDENTIAL_KEYS
from evaluation.commerce.meta_marketing_insights import normalize_supplied_insights

PROVIDER = "meta_marketing_insights"
DOCUMENTED_EDGES = (
    "GET /act_{ad_account_id}/insights",
    "GET /{campaign_id}/insights",
    "GET /{ad_set_id}/insights",
    "GET /{ad_id}/insights",
)


def _meta_keys(loaded_keys: Sequence[str]) -> tuple[str, ...]:
    names = []
    for key in loaded_keys:
        if not isinstance(key, str):
            continue
        folded = key.strip().upper()
        if folded.startswith("META_") or folded.startswith("FACEBOOK_"):
            names.append(folded)
    return tuple(names)


def explain_operational_readiness(
    *,
    loaded_keys: Sequence[str] = (),
    approval_granted: bool = False,
) -> dict[str, Any]:
    """Report why a live read cannot run. Values of any keys are ignored."""
    approved = tuple(sorted(RESEARCH_CREDENTIAL_KEYS))
    present = _meta_keys(loaded_keys)
    allowlisted = tuple(key for key in approved if key.startswith("META_") or key.startswith("FACEBOOK_"))
    if not approval_granted:
        status = "approval_unavailable"
    elif not allowlisted or not present:
        status = "credential_unavailable"
    else:
        status = "transport_not_wired"
    return {
        "provider": PROVIDER,
        "status": status,
        "read_only": True,
        "documented_edges": list(DOCUMENTED_EDGES),
        "approved_allowlist_has_meta_key": bool(allowlisted),
        "meta_key_names_present": list(present),
        "credential_values_read": False,
        "provider_call": False,
        "fixture_fallback": False,
        "rows": [],
        "mutated": False,
        "forbidden": [
            "campaign_create",
            "campaign_edit",
            "spend_change",
            "targeting_change",
            "messaging",
            "customer_list",
            "insights_post_report_run",
        ],
    }


def operational_read(
    *,
    loaded_keys: Sequence[str] = (),
    approval_granted: bool = False,
    transport: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Blocked operational read. The injected transport is not called."""
    decision = explain_operational_readiness(loaded_keys=loaded_keys, approval_granted=approval_granted)
    decision["transport_called"] = False
    if transport is not None and decision["status"] == "transport_not_wired":
        decision["transport_called"] = False
    return decision


def read_supplied_fixture(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize a caller-supplied document. This is not an operational fallback."""
    return normalize_supplied_insights(payload)
