"""Read-only Meta Marketing API Insights evidence.

This is reporting for one authorized advertiser account. It is not the public
Meta Ad Library, not market-wide demand, and not an opportunity score.

Official pages consulted on 2026-10-14:
- Ads Insights API, updated 2026-04-27. Examples use Graph v26.0.
  https://developers.facebook.com/docs/marketing-api/insights/
  GET edges: ad account, campaign, ad set, and ad. A sample row has
  date_start, date_stop, impressions, and spend. clicks is documented.
- ads_read permission reference.
  https://developers.facebook.com/docs/permissions/reference/ads_read
  The permission reads insights for accounts the app owns or was granted.
- Ad account insights reference, updated 2026-08-06.
  https://developers.facebook.com/docs/marketing-api/reference/ad-account/insights
  account_currency is the ad-account currency. POST creates an AdReportRun.
- Limits and best practices, updated 2026-05-05.
  https://developers.facebook.com/docs/marketing-api/insights/best-practices/
  "We report ad insights data in the ad account’s timezone."
  "Insights refresh every 15 minutes and do not change after 28 days of
  being reported." Metrics may keep updating for a couple of days after an
  ad completes. Error 100 / 1487534 is the data-per-call limit. The throttle
  header is x-fb-ads-insights-throttle. No numeric quota is stated.
- Ads Insights API error codes, updated 2026-05-21.
  https://developers.facebook.com/docs/marketing-api/insights/error-codes/
  Error 4 / 1504022 is too many requests. Error 100 / 3191001 is permission.
- Metric availability update, published 2025-10-16, effective 2026-01-12.
  https://developers.facebook.com/blog/post/2025/10/16/ads-insights-api-metric-availability-updates/
  7d_view and 28d_view are deprecated. This module does not request a window.

Still unknown: a numeric rate quota, the maximum custom time_range, an IANA
zone field, and the advertiser's retention duty. Old Graph versions are not used.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

from evaluation.commerce.intelligence_adapter_plan import NormalizedEvidenceRecord
from evaluation.companyos.approval_ledger import default_approval_policies, simulate_action

SCHEMA = "MarketOS.MetaMarketingInsightsEvidence.v1"
SOURCE = "meta_marketing_api_insights"
DOCUMENTED_GRAPH_VERSION = "v26.0"
ADAPTER_WINDOW_DAYS = 90
IMMUTABLE_AFTER_DAYS = 28
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DECIMAL = re.compile(r"^(?:0|[1-9]\d{0,12})(?:\.\d{1,6})?$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ACTION = re.compile(r"^[a-z0-9_]{1,40}$")
_SCOPE = re.compile(r"^fixture-[a-z0-9-]{1,40}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PERSONAL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b\d{3}-\d{3}-\d{4}\b")
_UNSAFE_KEYS = frozenset({"access_token", "api_key", "authorization", "password", "raw_payload", "secret", "token"})
_DEMOGRAPHIC_KEYS = frozenset({"age", "country", "gender", "region", "dma"})
_METRIC_FIELDS = ("impressions", "clicks", "spend")
_ERROR_KINDS = {
    (4, 1504022): "rate_limited",
    (100, 1487534): "data_per_call_limit",
    (100, 1504018): "timeout",
    (100, 3191001): "permission_denied",
}
_AUTHORITY_FALSE = (
    "spend_change_authorized",
    "campaign_created",
    "campaign_edited",
    "targeting_changed",
    "messages_sent",
    "customer_list_used",
    "purchase_intent",
    "independently_verified_sales",
    "ad_library_evidence",
    "market_wide_demand",
    "opportunity_rescore",
    "provider_call",
    "credentials_read",
)
_ALLOWED_USE = "account_performance_review"
_REJECTED_USES = frozenset(
    {
        "market_demand",
        "competitor_intelligence",
        "product_opportunity_attention",
        "verified_sales",
        "ad_launch",
        "purchase_intent",
    }
)


def _unsafe(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).strip().lower().replace("-", "_") in _UNSAFE_KEYS:
                raise ValueError("unsafe insights input")
            _unsafe(item)
        return
    if isinstance(value, list):
        for item in value:
            _unsafe(item)
        return
    if isinstance(value, str) and (_CONTROL.search(value) or _PERSONAL.search(value) or "bearer " in value.lower()):
        raise ValueError("unsafe insights input")


def _day(value: Any) -> date | None:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _require_day(value: Any) -> date:
    parsed = _day(value)
    if parsed is None:
        raise ValueError("unsafe insights input")
    return parsed


def _decimal(value: Any) -> str | None:
    if isinstance(value, bool) or isinstance(value, float) or value in (None, ""):
        return None
    text = str(value).strip() if isinstance(value, (str, int)) else ""
    if not _DECIMAL.fullmatch(text):
        return None
    return text


def _actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, Mapping):
            continue
        name = item.get("action_type")
        count = _decimal(item.get("value"))
        if not isinstance(name, str) or not _ACTION.fullmatch(name) or count is None:
            continue
        rows.append(
            {
                "action_type": name,
                "value": count,
                "platform_reported": True,
                "independently_verified_sales": False,
            }
        )
    return rows


def _row(item: Mapping[str, Any], *, as_of: date | None) -> tuple[dict[str, Any] | None, str | None]:
    start = _day(item.get("date_start"))
    stop = _day(item.get("date_stop"))
    if start is None or stop is None or stop < start:
        return None, "date_unparsed"
    if (stop - start).days > ADAPTER_WINDOW_DAYS:
        return None, "adapter_window_exceeded"
    if as_of is not None and start > as_of:
        return None, "not_yet_reported"
    metrics = {name: _decimal(item.get(name)) for name in _METRIC_FIELDS}
    if all(value is None for value in metrics.values()):
        return None, "metrics_absent"
    currency = item.get("account_currency")
    age = None if as_of is None else (as_of - stop).days
    if age is None:
        stability = "not_assessed"
    elif age >= IMMUTABLE_AFTER_DAYS:
        stability = "officially_unchanged_after_28_days"
    else:
        stability = "may_still_refresh"
    return {
        "date_start": start.isoformat(),
        "date_stop": stop.isoformat(),
        "impressions": metrics["impressions"],
        "clicks": metrics["clicks"],
        "spend": metrics["spend"],
        "field_status": {name: "supplied" if metrics[name] is not None else "unavailable" for name in _METRIC_FIELDS},
        "ctr": _decimal(item.get("ctr")),
        "ctr_recomputed": False,
        "account_currency": currency if isinstance(currency, str) and _CURRENCY.fullmatch(currency) else None,
        "platform_reported_actions": _actions(item.get("actions")),
        "account_id_stored": False,
        "demographic_breakdown_stored": False,
        "timezone_basis": "ad_account_timezone",
        "timezone_name": None,
        "attribution_window_requested": False,
        "reporting_stability": stability,
        "combined_with_other_currencies": False,
    }, None


def _scope_label(value: Any) -> str | None:
    if not isinstance(value, str) or not _SCOPE.fullmatch(value):
        return None
    return value


def approval_dependency() -> dict[str, Any]:
    """Read the canonical ledger. This does not grant a live call."""
    policy = next(item for item in default_approval_policies() if item.request_type == "provider_call")
    simulation = simulate_action("provider_call", requested_budget=0)
    launch = simulate_action("ad_launch", requested_budget=0)
    return {
        "request_type": "provider_call",
        "blocked_in_current_mode": policy.blocked_in_current_mode,
        "budget_per_run": format(policy.budget_cap.per_run, "f"),
        "budget_monthly": format(policy.budget_cap.monthly, "f"),
        "simulation_result": simulation.result,
        "can_execute": bool(simulation.can_be_approved_now),
        "ad_launch_result": launch.result,
        "ad_launch_can_execute": bool(launch.can_be_approved_now),
    }


def _evidence(status: str, rows: list[dict[str, Any]], extra: Mapping[str, Any]) -> dict[str, Any]:
    currencies = {row["account_currency"] for row in rows if row["account_currency"]}
    record = NormalizedEvidenceRecord(
        source_provider=SOURCE,
        source_method="GET insights",
        source_url_or_id_placeholder="graph://meta-marketing-insights/supplied-fixture",
        captured_at_placeholder="not_observed",
        raw_record_ref_placeholder="not_retained",
        normalized_fields={
            "schema": SCHEMA,
            "documented_graph_version": DOCUMENTED_GRAPH_VERSION,
            "data_scope": "authorized_advertiser_account_only",
            "rows": rows,
            "row_count": len(rows),
            "single_currency": len(currencies) <= 1,
            "combined_spend": None,
            **dict(extra),
        },
        confidence="supplied_fixture",
        limitations=(
            "authorized_account_only",
            "platform_reported_not_independently_verified_sales",
            "not_consumer_purchase_intent",
            "not_market_wide_demand",
            "not_meta_ad_library_evidence",
            "not_an_opportunity_score",
            "numeric_rate_limit_not_stated",
            "timezone_name_not_in_consulted_response_fields",
            "retention_duty_not_stated",
        ),
        terms_notes="ads_read is the documented read permission. A fixture is not an authorized account observation.",
        privacy_notes="Account ids, paging cursors, demographic breakdowns, and raw payloads are not stored.",
        evidence_category="ProviderRunEvidence",
        can_feed_reports=False,
    )
    return {
        "schema": SCHEMA,
        "status": status,
        "evidence_mode": "supplied_fixture",
        "live_observation": False,
        "read_only": True,
        "provider_call": False,
        "credentials_read": False,
        "fixture_used_as_operational_fallback": False,
        "authority": {key: False for key in _AUTHORITY_FALSE},
        "evidence": record.to_dict(),
        "official_numeric_rate_limit": "not_stated",
        "official_timezone_basis": "ad_account_timezone",
        "official_refresh": "every_15_minutes",
        "official_immutability": "unchanged_after_28_days_of_being_reported",
        "retries": 0,
    }


def normalize_supplied_insights(
    payload: Mapping[str, Any] | None,
    *,
    expected_account_scope: str | None = None,
    requested_since: str | None = None,
    requested_until: str | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Map one supplied insights document. This does not call Meta."""
    if not isinstance(payload, Mapping):
        raise ValueError("unsafe insights input")
    _unsafe(payload)
    expected = None if expected_account_scope is None else _scope_label(expected_account_scope)
    if expected_account_scope is not None and expected is None:
        raise ValueError("unsafe insights input")
    since = None if requested_since is None else _require_day(requested_since)
    until = None if requested_until is None else _require_day(requested_until)
    observed = None if as_of is None else _require_day(as_of)
    if since is not None and until is not None and until < since:
        raise ValueError("unsafe insights input")

    error = payload.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        subcode = error.get("error_subcode")
        pair = (
            (code, subcode)
            if isinstance(code, int)
            and not isinstance(code, bool)
            and isinstance(subcode, int)
            and not isinstance(subcode, bool)
            else None
        )
        kind = _ERROR_KINDS.get(pair, "provider_error") if pair is not None else "provider_error"
        return _evidence(kind, [], {"provider_error_class": kind, "paging_retained": False, "truncated": False})

    supplied_scope = payload.get("account_scope")
    if expected is not None and _scope_label(supplied_scope) != expected:
        return _evidence("account_scope_mismatch", [], {"account_scope_accepted": False, "paging_retained": False})

    rows_in = payload.get("data")
    if not isinstance(rows_in, list):
        raise ValueError("unsafe insights input")
    demographic = False
    kept: list[dict[str, Any]] = []
    rejected = {"date_unparsed": 0, "time_range_mismatch": 0, "not_yet_reported": 0}
    for item in rows_in[:50]:
        if not isinstance(item, Mapping):
            rejected["date_unparsed"] += 1
            continue
        if any(key in item for key in _DEMOGRAPHIC_KEYS):
            demographic = True
        parsed, reason = _row(item, as_of=observed)
        if parsed is None:
            if reason in rejected:
                rejected[reason] += 1
            continue
        if (
            since is not None
            and until is not None
            and (parsed["date_start"] != since.isoformat() or parsed["date_stop"] != until.isoformat())
        ):
            rejected["time_range_mismatch"] += 1
            continue
        kept.append(parsed)
    currencies = {row["account_currency"] for row in kept if row["account_currency"]}
    mixed = len(currencies) > 1
    for row in kept:
        row["combined_with_other_currencies"] = mixed
    if kept:
        status = "supplied_fixture"
    elif rejected["time_range_mismatch"]:
        status = "time_range_mismatch"
    else:
        status = "unavailable"
    paging = payload.get("paging")
    truncated = isinstance(paging, Mapping) and bool(paging)
    return _evidence(
        status,
        kept,
        {
            "demographic_breakdown_discarded": demographic,
            "paging_retained": False,
            "truncated": truncated,
            "rejected_row_counts": rejected,
            "account_scope_accepted": expected is not None,
        },
    )


def account_performance_view(document: Mapping[str, Any], *, claimed_use: str) -> dict[str, Any]:
    """Consume account evidence without treating it as market demand."""
    rejected = {
        "claimed_use": claimed_use if claimed_use in _REJECTED_USES else "unsupported",
        "data_scope": "authorized_advertiser_account_only",
        "market_wide": False,
        "competitor_intelligence": False,
        "purchase_intent": False,
        "verified_sales": False,
        "ad_library_evidence": False,
        "opportunity_attention": False,
        "ad_launch_authorized": False,
        "rows_released": False,
        "rows": [],
        "combined_spend": None,
    }
    if claimed_use != _ALLOWED_USE:
        return {"status": "claim_rejected", **rejected}
    evidence = document.get("evidence") if isinstance(document, Mapping) else None
    fields = evidence.get("normalized_fields", {}) if isinstance(evidence, Mapping) else {}
    releasable = (
        isinstance(document, Mapping)
        and document.get("status") == "supplied_fixture"
        and isinstance(evidence, Mapping)
        and evidence.get("evidence_category") == "ProviderRunEvidence"
        and isinstance(fields, Mapping)
        and fields.get("data_scope") == "authorized_advertiser_account_only"
    )
    if not releasable:
        return {"status": "evidence_not_releasable", **rejected, "claimed_use": _ALLOWED_USE}
    rows = fields.get("rows", [])
    return {
        "status": "account_performance_only",
        "claimed_use": _ALLOWED_USE,
        "data_scope": "authorized_advertiser_account_only",
        "market_wide": False,
        "competitor_intelligence": False,
        "purchase_intent": False,
        "verified_sales": False,
        "ad_library_evidence": False,
        "opportunity_attention": False,
        "ad_launch_authorized": False,
        "rows_released": True,
        "rows": rows if isinstance(rows, list) else [],
        "combined_spend": None,
    }


def build_blocked_get_plan(*, account_scope: str, since: str, until: str) -> dict[str, Any]:
    """Describe a GET insights request that cannot be sent.

    The plan never includes an account id, a token, or a POST body. Approval
    Ledger still blocks provider_call, so this is not a live request.
    """
    if _scope_label(account_scope) is None:
        raise ValueError("unsafe insights input")
    start = _require_day(since)
    stop = _require_day(until)
    if stop < start or (stop - start).days > ADAPTER_WINDOW_DAYS:
        raise ValueError("unsafe insights input")
    dependency = approval_dependency()
    return {
        "method": "GET",
        "edge": "/insights",
        "graph_version_documented": DOCUMENTED_GRAPH_VERSION,
        "account_id_included": False,
        "account_scope_label": account_scope,
        "since": start.isoformat(),
        "until": stop.isoformat(),
        "fields": ["impressions", "clicks", "spend", "date_start", "date_stop", "account_currency"],
        "breakdowns": [],
        "attribution_window_requested": False,
        "post_allowed": False,
        "status": "blocked_by_approval_ledger" if dependency["blocked_in_current_mode"] else "transport_not_wired",
        "provider_call": False,
        "credentials_read": False,
        "data_scope": "authorized_advertiser_account_only",
        "approval": dependency,
    }
