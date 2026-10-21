"""Operational gate for Meta Marketing API Insights.

Live GET is not wired. The Approval Ledger blocks provider_call in the current
mode, and the approved research credential allowlist has no Meta key. A
supplied fixture is not substituted when an operational read is blocked.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from backend.research.credentials import RESEARCH_CREDENTIAL_KEYS
from evaluation.commerce.meta_marketing_insights import (
    approval_dependency,
    build_blocked_get_plan,
    normalize_supplied_insights,
)

PROVIDER = "meta_marketing_insights"
DOCUMENTED_EDGES = (
    "GET /act_{ad_account_id}/insights",
    "GET /{campaign_id}/insights",
    "GET /{ad_set_id}/insights",
    "GET /{ad_id}/insights",
)


def _meta_key_count(loaded_keys: Sequence[str]) -> int:
    count = 0
    for key in loaded_keys:
        if not isinstance(key, str):
            continue
        folded = key.strip().upper()
        if folded.startswith("META_") or folded.startswith("FACEBOOK_"):
            count += 1
    return count


def explain_operational_readiness(*, loaded_keys: Sequence[str] = ()) -> dict[str, Any]:
    """Report the canonical block. Key values are never read."""
    dependency = approval_dependency()
    allowlisted = any(key.startswith("META_") or key.startswith("FACEBOOK_") for key in RESEARCH_CREDENTIAL_KEYS)
    blocked = dependency["blocked_in_current_mode"] or not dependency["can_execute"] or not allowlisted
    return {
        "provider": PROVIDER,
        "status": "blocked_by_approval_ledger" if blocked else "transport_not_wired",
        "read_only": True,
        "documented_edges": list(DOCUMENTED_EDGES),
        "approval": dependency,
        "approved_allowlist_has_meta_key": allowlisted,
        "supplied_meta_key_name_count": _meta_key_count(loaded_keys),
        "credential_values_read": False,
        "provider_call": False,
        "fixture_fallback": False,
        "rows": [],
        "mutated": False,
        "dependency": "provider_call is blocked_in_current_mode with a zero budget, and RESEARCH_CREDENTIAL_KEYS has no Meta key",
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
    transport: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Blocked operational read. The injected transport is not called."""
    del transport
    decision = explain_operational_readiness(loaded_keys=loaded_keys)
    decision["transport_called"] = False
    return decision


def blocked_get_plan(*, account_scope: str, since: str, until: str) -> dict[str, Any]:
    """Return a GET-only plan. No transport is called and no account id is stored."""
    return build_blocked_get_plan(account_scope=account_scope, since=since, until=until)


def read_supplied_fixture(payload: Mapping[str, Any] | None, **options: Any) -> dict[str, Any]:
    """Normalize a caller-supplied document. This is not an operational fallback."""
    return normalize_supplied_insights(payload, **options)
