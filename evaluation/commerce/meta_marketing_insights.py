"""Read-only Meta Marketing API Insights evidence.

This is the operator's own authorized-account reporting shape. It is not the
public Meta Ad Library, not consumer attention, and not an opportunity score.

Official pages consulted on 2026-10-14:
- Ads Insights API, updated 2026-04-27, examples use Graph v26.0.
  GET /{ad-account-id}/insights, /{campaign-id}/insights, /{ad-set-id}/insights,
  and /{ad-id}/insights. Default GET metrics are typically the past 30 days.
  A documented response includes date_start, date_stop, impressions, and spend.
  clicks is a documented field. ctr is described as a derived metric.
- ads_read: access to Ads Insights for ad accounts the app owns or was granted.
  Allowed use includes custom dashboards and data analytics. Examples name
  Impressions, Conversions, Spend, Clicks, and Reach as performance data.
- Ad account insights reference: account_currency is the ad account currency.
  date_start and date_stop follow the selected reporting range. Default fields
  are impressions and spend. POST to this edge creates an AdReportRun. This
  module never builds that POST.
- Limits and best practices, updated 2026-05-05: sync GET and async POST share
  a rate limit. Error 4 / 1504022 means too many requests. No numeric quota is
  stated. Reach with breakdowns older than 13 months is omitted.
- Metric availability update, 2025-10-16, effective 2026-01-12: 7d_view and
  28d_view are deprecated. This module does not request attribution windows.

Unknown, and not filled in: the numeric rate limit, the maximum custom
time_range, the advertiser's data-retention duty, and whether insight dates
are UTC or the ad account timezone.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Mapping

from evaluation.commerce.intelligence_adapter_plan import NormalizedEvidenceRecord

SCHEMA = "MarketOS.MetaMarketingInsightsEvidence.v1"
SOURCE = "meta_marketing_api_insights"
DOCUMENTED_GRAPH_VERSION = "v26.0"
ADAPTER_WINDOW_DAYS = 90
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ACTION = re.compile(r"^[a-z0-9_]{1,40}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_PERSONAL = re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|\b\d{3}-\d{3}-\d{4}\b")
_UNSAFE_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "password",
        "raw_payload",
        "secret",
        "token",
    }
)
_DEMOGRAPHIC_KEYS = frozenset({"age", "country", "gender", "region", "dma"})
_METRIC_FIELDS = ("impressions", "clicks", "spend")
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
    "opportunity_rescore",
    "provider_call",
    "credentials_read",
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


def _metric(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value[:20]:
        if not isinstance(item, Mapping):
            continue
        name = item.get("action_type")
        count = _metric(item.get("value"))
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


def _row(item: Mapping[str, Any]) -> dict[str, Any] | None:
    start = _day(item.get("date_start"))
    stop = _day(item.get("date_stop"))
    if start is None or stop is None or stop < start:
        return None
    if (stop - start).days > ADAPTER_WINDOW_DAYS:
        return None
    metrics = {name: _metric(item.get(name)) for name in _METRIC_FIELDS}
    if all(value is None for value in metrics.values()):
        return None
    currency = item.get("account_currency")
    ctr = _metric(item.get("ctr"))
    return {
        "date_start": start.isoformat(),
        "date_stop": stop.isoformat(),
        "impressions": metrics["impressions"],
        "clicks": metrics["clicks"],
        "spend": metrics["spend"],
        "ctr": None if ctr is None else ctr,
        "ctr_recomputed": False,
        "account_currency": currency if isinstance(currency, str) and _CURRENCY.fullmatch(currency) else None,
        "platform_reported_actions": _actions(item.get("actions")),
        "account_id_stored": False,
        "demographic_breakdown_stored": False,
        "timezone": "not_stated_on_consulted_pages",
        "attribution_window_requested": False,
    }


def normalize_supplied_insights(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Map one supplied insights document. This does not call Meta."""
    if not isinstance(payload, Mapping):
        raise ValueError("unsafe insights input")
    _unsafe(payload)
    rows_in = payload.get("data")
    if not isinstance(rows_in, list):
        raise ValueError("unsafe insights input")
    demographic = False
    kept: list[dict[str, Any]] = []
    for item in rows_in[:50]:
        if not isinstance(item, Mapping):
            continue
        if any(key in item for key in _DEMOGRAPHIC_KEYS):
            demographic = True
        parsed = _row(item)
        if parsed is not None:
            kept.append(parsed)
    authority = {key: False for key in _AUTHORITY_FALSE}
    record = NormalizedEvidenceRecord(
        source_provider=SOURCE,
        source_method="GET insights",
        source_url_or_id_placeholder="graph://meta-marketing-insights/supplied-fixture",
        captured_at_placeholder="not_observed",
        raw_record_ref_placeholder="not_retained",
        normalized_fields={
            "schema": SCHEMA,
            "documented_graph_version": DOCUMENTED_GRAPH_VERSION,
            "rows": kept,
            "row_count": len(kept),
            "demographic_breakdown_discarded": demographic,
            "paging_retained": False,
        },
        confidence="supplied_fixture",
        limitations=(
            "platform_reported_not_independently_verified_sales",
            "not_consumer_purchase_intent",
            "not_meta_ad_library_evidence",
            "not_an_opportunity_score",
            "numeric_rate_limit_not_stated",
            "timezone_not_stated_on_consulted_pages",
        ),
        terms_notes="ads_read is the documented read permission. This fixture is not an authorized account observation.",
        privacy_notes="Account ids, paging cursors, demographic breakdowns, and raw payloads are not stored.",
        evidence_category="ProviderRunEvidence",
        can_feed_reports=False,
    )
    return {
        "schema": SCHEMA,
        "status": "supplied_fixture" if kept else "unavailable",
        "evidence_mode": "supplied_fixture",
        "live_observation": False,
        "read_only": True,
        "provider_call": False,
        "credentials_read": False,
        "fixture_used_as_operational_fallback": False,
        "authority": authority,
        "evidence": record.to_dict(),
        "official_numeric_rate_limit": "not_stated",
        "retries": 0,
    }
