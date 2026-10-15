"""Amazon category-bestseller research adapter (unavailable live discovery).

Historical behavior scraped Amazon Best Sellers HTML and fell back to mock
rows. That scrape path is removed.

Capability decision (official docs, access date 2026-10-14): Amazon does not
document a commercially eligible category Best Sellers *list/feed* API for
MarketOS multi-client product research. SP-API Catalog Items expose per-item
``salesRanks`` after ASIN/search hits (seller/vendor Product Listing role).
Creators API ``SearchItems`` / ``GetBrowseNodes`` expose catalog search and
browse-node hierarchy (Associates + qualifying sales); ``SortBy`` has no
BestSellers value. Neither is a Best Sellers page equivalent.

Therefore:
- Operational ``fetch()`` returns ``[]`` (never fixtures, never scrape).
- Default ``collect_amazon_bestseller_evidence()`` returns
  ``status=unavailable`` with an explicit blocker list.
- Fixtures / manual import / offline fake-transport normalization remain only
  behind explicit ``mode=`` selection for tests or demos — never as silent
  operational research and never labeled live-validated.

Registers itself with the SignalEngine as ``amazon_bestsellers``.
"""
from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

_log = logging.getLogger(__name__)

SOURCE = "amazon_bestsellers"
FIXTURE_SOURCE = "amazon_bestsellers_mock"  # research consumers filter this as synthetic
MANUAL_SOURCE = "amazon_bestsellers_manual_import"  # explicit operator snapshot; never live
OFFLINE_TRANSPORT_SOURCE = "amazon_bestsellers_offline_transport"
LIVE_FLAG = "MARKETOS_AMAZON_BESTSELLERS_LIVE"
DEMO_FLAG = "MARKETOS_AMAZON_BESTSELLERS_DEMO"
PROVIDER_ENV = "MARKETOS_AMAZON_BESTSELLERS_PROVIDER"
DEFAULT_MARKETPLACE = "US"
DEFAULT_MARKETPLACE_ID = "ATVPDKIKX0DER"  # documented Amazon US marketplace id

# Injected authority / volume claims are never copied onto normalized rows.
_STRIPPED_AUTHORITY_FIELDS: frozenset[str] = frozenset(
    {
        "sales_volume",
        "unit_sales",
        "estimated_units",
        "estimated_unit_sales",
        "units_sold",
        "demand_proof",
        "profit",
        "revenue",
        "gmv",
        "launch_authority",
        "observed",
    }
)

CAPABILITY_DECISION = {
    "category_bestseller_discovery": "unavailable",
    "reason_code": "no_documented_category_bestseller_list_api",
    "access_date_utc": "2026-10-14",
    "reconfirmed_access_date_utc": "2026-10-15",
    "operator_context": "multi_client_commercial_product_research_not_seller_of_record",
}

LIVE_PREREQUISITES: tuple[str, ...] = (
    "companyos_approval_ledger_provider_call_or_web_data_acquisition",
    "credential_registry_entry_without_secret_values",
    "resource_execution_governor_budget_and_rate_cap",
    "trustos_provider_and_privacy_gate",
    "documented_category_bestseller_list_api_or_explicit_rescope",
)

OFFICIAL_REFERENCES: tuple[str, ...] = (
    "https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference",
    "https://developer-docs.amazon.com/sp-api/docs/role-mappings",
    "https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction",
    "https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/search-items",
    "https://affiliate-program.amazon.com/creatorsapi/docs/en-us/api-reference/operations/get-browse-nodes",
)

_CACHE: list[dict[str, Any]] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600  # 1 hour
_LAST_FETCH_STATUS: dict[str, Any] = {
    "status": "unavailable",
    "reason_code": CAPABILITY_DECISION["reason_code"],
    "live_validated": False,
    "records_returned": 0,
}

# Categories remain configuration metadata for explicit fixture rows only (no HTTP).
_CATEGORIES = os.getenv(
    "AMAZON_BESTSELLER_CATEGORIES",
    "beauty,electronics,home-kitchen,sports-outdoors,toys-games,pet-supplies,baby-products",
).split(",")

_FIXTURE_PRODUCTS: tuple[dict[str, Any], ...] = (
    {"product": "Wireless Earbuds Pro", "category": "electronics", "rank": 1},
    {"product": "Vitamin D3 5000 IU", "category": "health", "rank": 2},
    {"product": "Air Fryer XL 5.8QT", "category": "home-kitchen", "rank": 3},
    {"product": "Resistance Bands Set", "category": "sports-outdoors", "rank": 4},
    {"product": "LED Strip Lights", "category": "home-kitchen", "rank": 5},
    {"product": "Portable Charger 20000", "category": "electronics", "rank": 6},
    {"product": "Collagen Peptides", "category": "health", "rank": 7},
    {"product": "Yoga Mat Non Slip", "category": "sports-outdoors", "rank": 8},
    {"product": "Automatic Pet Feeder", "category": "pet-supplies", "rank": 1},
    {"product": "Dog Puzzle Slow Feeder Bowl", "category": "pet-supplies", "rank": 2},
    {"product": "Pet Grooming Deshedding Glove", "category": "pet-supplies", "rank": 3},
    {"product": "Silicone Baby Feeding Set", "category": "baby-products", "rank": 1},
    {"product": "Baby Bath Toy Set", "category": "baby-products", "rank": 2},
)


def _utc_now(clock: Callable[[], float] | None = None) -> str:
    stamp = float(clock() if clock is not None else time.time())
    if not math.isfinite(stamp):
        return ""
    return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _rank_score(rank: Any) -> float | None:
    if isinstance(rank, bool) or rank is None:
        return None
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    if value == 0:
        return 0.0
    return round(max(0.1, 1.0 - (value - 1) * 0.08), 2)


def _fixture_rows(*, observed_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _FIXTURE_PRODUCTS:
        rank = item.get("rank")
        score = _rank_score(rank)
        rows.append(
            {
                "product": item["product"],
                "category": item["category"],
                "rank": rank,
                "score": score,
                "source": FIXTURE_SOURCE,
                "platform": "amazon",
                "marketplace": DEFAULT_MARKETPLACE,
                "marketplace_id": DEFAULT_MARKETPLACE_ID,
                "product_url": None,
                "price": None,
                "currency": None,
                "availability": None,
                "observed_at": observed_at,
                "evidence_mode": "fixture",
                "observation_kind": "fixture_bestseller_rank",
                "authenticity": "synthetic_or_unverified_fixture",
                "rank_semantics": "relative_bestseller_rank_not_unit_sales",
                "live_validated": False,
                "network_calls": False,
                "mutated": False,
            }
        )
    return rows


def _capability_blockers() -> list[str]:
    return [
        "html_bestseller_scrape_disabled",
        "no_documented_category_bestseller_list_api",
        "creators_api_searchitems_sortby_has_no_bestsellers_value",
        "creators_api_getbrowsenodes_is_hierarchy_not_ranked_asin_list",
        "sp_api_catalog_salesranks_are_per_item_not_category_feed",
        "sp_api_catalog_items_requires_seller_or_vendor_product_listing_role",
        "creators_api_requires_amazon_associates_enrollment_and_qualifying_sales",
        "bestseller_rank_is_relative_not_unit_sales_or_demand_proof",
        "allow_network_alone_is_not_approval_authority",
        *LIVE_PREREQUISITES,
    ]


def explain_amazon_bestsellers_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    allow_network: bool = False,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Explain why live Amazon category-bestseller research is unavailable."""
    env = os.environ if environ is None else environ
    live_flag = str(env.get(LIVE_FLAG, "0")).strip() == "1"
    demo_flag = str(env.get(DEMO_FLAG, "0")).strip() == "1"
    provider = str(env.get(PROVIDER_ENV, "")).strip().lower()
    transport_ready = transport is not None and callable(getattr(transport, "fetch_catalog_ranks", None))
    offline = getattr(transport, "offline_fixture", False) is True if transport is not None else False
    blockers = _capability_blockers()
    if not live_flag:
        blockers.append(f"{LIVE_FLAG}_disabled")
    if not allow_network:
        blockers.append("allow_network_false")
    if not transport_ready:
        blockers.append("injected_transport_required_for_offline_contract_tests_only")
    elif not offline and live_flag and allow_network:
        blockers.append("live_provider_http_not_enabled_no_category_bestseller_endpoint")

    # Primary operational status: unavailable. Offline transport readiness is
    # only for explicit contract-test normalization, not live discovery.
    status = "unavailable_no_category_bestseller_api"
    if live_flag and allow_network and transport_ready and offline:
        status = "offline_transport_contract_ready"
    elif live_flag and allow_network and transport_ready:
        status = "blocked_no_documented_live_bestseller_endpoint"

    return {
        "provider": provider or "unset",
        "live_flag_enabled": live_flag,
        "demo_flag_enabled": demo_flag,
        "allow_network": bool(allow_network),
        "transport_injected": transport_ready,
        "transport_offline_fixture": offline,
        "status": status,
        "capability_decision": dict(CAPABILITY_DECISION),
        "live_prerequisites": list(LIVE_PREREQUISITES),
        "read_only": True,
        "mutated": False,
        "html_scraping": False,
        "credentials_inspected": False,
        "secrets_printed": False,
        "approval_ledger_authority": False,
        "supported": {
            "explicit_fixture_demo_rows": True,
            "manual_import_normalization": True,
            "injected_offline_transport_normalization": True,
            "operational_empty_fetch": True,
        },
        "unsupported": {
            "amazon_html_best_sellers_scrape": True,
            "ungated_live_category_bestseller_browse": True,
            "silent_fixture_as_operational_research": True,
            "mock_rows_as_observed_evidence": True,
            "rank_as_unit_sales_or_profit": True,
            "labeling_catalog_search_or_per_asin_salesranks_as_bestseller_feed": True,
        },
        "adjacent_not_bestseller_feed": {
            "sp_api_catalog_items_salesranks_per_asin": (
                "Per-item ranks when ASINs are already known; requires SP-API "
                "developer registration + selling-partner Product Listing role."
            ),
            "creators_api_searchitems": (
                "Keyword/browseNode catalog search; SortBy has no BestSellers; "
                "requires Associates + qualifying sales."
            ),
            "creators_api_getbrowsenodes": "Browse-node hierarchy only, not ranked ASIN lists.",
        },
        "official_references": list(OFFICIAL_REFERENCES),
        "blockers": blockers,
    }


def last_fetch_status() -> dict[str, Any]:
    """Return the last SignalEngine ``fetch()`` status envelope (never live)."""
    return dict(_LAST_FETCH_STATUS)


def normalize_rank_record(
    raw: Mapping[str, Any],
    *,
    evidence_mode: str,
    observed_at: str = "",
    default_marketplace: str = DEFAULT_MARKETPLACE,
) -> dict[str, Any] | None:
    """Normalize one Amazon rank/catalog row without inventing missing fields."""
    if evidence_mode not in {"fixture", "manual_import", "offline_transport"}:
        raise ValueError("evidence_mode is invalid")
    product = raw.get("product") or raw.get("title") or raw.get("itemName")
    if not isinstance(product, str) or not product.strip():
        return None
    product = " ".join(product.split())[:120]

    category = raw.get("category") or raw.get("browse_node") or raw.get("classification")
    category_text = " ".join(str(category).split())[:80] if category not in (None, "") else None

    rank_value = raw.get("rank")
    if rank_value is None:
        rank_value = raw.get("sales_rank")
    rank: int | None
    if rank_value is None or rank_value == "":
        rank = None
    elif isinstance(rank_value, bool):
        return None
    else:
        try:
            rank = int(rank_value)
        except (TypeError, ValueError):
            return None
        if rank < 0:
            return None

    price_value = raw.get("price")
    price: float | None
    if price_value in (None, ""):
        price = None
    elif isinstance(price_value, bool):
        price = None
    else:
        try:
            price = float(price_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(price):
            return None

    currency = raw.get("currency")
    currency_text = str(currency).strip().upper() if isinstance(currency, str) and currency.strip() else None
    if price is not None and currency_text is None:
        price = None

    marketplace = raw.get("marketplace") or default_marketplace
    marketplace_text = str(marketplace).strip().upper() if marketplace not in (None, "") else None
    marketplace_id = raw.get("marketplace_id")
    marketplace_id_text = str(marketplace_id).strip() if marketplace_id not in (None, "") else None

    product_url = raw.get("product_url") or raw.get("url") or raw.get("detail_page_url")
    url_text = str(product_url).strip() if isinstance(product_url, str) and product_url.strip() else None
    availability = raw.get("availability")
    availability_text = str(availability).strip() if isinstance(availability, str) and availability.strip() else None

    stamp = raw.get("observed_at") if isinstance(raw.get("observed_at"), str) else observed_at
    if evidence_mode == "fixture":
        source = FIXTURE_SOURCE
        observation_kind = "fixture_bestseller_rank"
        authenticity = "synthetic_or_unverified_fixture"
    elif evidence_mode == "manual_import":
        source = MANUAL_SOURCE
        observation_kind = "manual_operator_snapshot_rank"
        authenticity = "operator_supplied_unverified"
    else:
        source = OFFLINE_TRANSPORT_SOURCE
        observation_kind = "offline_transport_contract_rank"
        authenticity = "offline_injected_transport_unverified"
    score = _rank_score(rank)
    row = {
        "product": product,
        "category": category_text,
        "rank": rank,
        "score": score,
        "source": source,
        "platform": "amazon",
        "marketplace": marketplace_text,
        "marketplace_id": marketplace_id_text,
        "product_url": url_text,
        "price": price,
        "currency": currency_text,
        "availability": availability_text,
        "observed_at": stamp or "",
        "evidence_mode": evidence_mode,
        "observation_kind": observation_kind,
        "authenticity": authenticity,
        "rank_semantics": "relative_bestseller_rank_not_unit_sales",
        "live_validated": False,
        "network_calls": False,
        "mutated": False,
    }
    for forbidden in _STRIPPED_AUTHORITY_FIELDS:
        row.pop(forbidden, None)
    return row


def collect_amazon_bestseller_evidence(
    *,
    mode: str = "unavailable",
    allow_network: bool = False,
    transport: Any | None = None,
    manual_rows: list[Mapping[str, Any]] | None = None,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Collect Amazon bestseller-style evidence with explicit status labels.

    Default ``mode="unavailable"`` is the operational research path: empty
    records and a precise unavailable/blocked envelope. Fixtures require
    ``mode="fixture"`` (or demo env + explicit fixture mode). Never performs
    live Amazon HTTP. ``allow_network`` alone is never approval authority.
    """
    bounded = max(0, min(int(limit), 100))
    readiness = explain_amazon_bestsellers_readiness(
        environ, allow_network=allow_network, transport=transport
    )
    observed_at = _utc_now(clock)
    warnings: list[str] = [
        "bestseller_rank_is_relative_not_unit_sales",
        "fixture_or_manual_is_not_observed_amazon_evidence",
        "signalengine_fetch_returns_empty_non_authoritative_list",
        "category_bestseller_discovery_unavailable_no_documented_api",
    ]

    if mode in {"unavailable", "operational", "default"}:
        return {
            "status": "unavailable",
            "evidence_mode": "unavailable",
            "records": [],
            "record_count": 0,
            "readiness": readiness,
            "warnings": warnings,
            "blockers": list(readiness.get("blockers") or []),
            "capability_decision": dict(CAPABILITY_DECISION),
            "html_scraping": False,
            "network_calls": False,
            "mutated": False,
            "live_validated": False,
            "read_only": True,
            "observed_at": observed_at,
            "error": {
                "code": CAPABILITY_DECISION["reason_code"],
                "message": (
                    "Amazon does not document a category Best Sellers list API "
                    "for this operator context. Per-item salesRanks and catalog "
                    "search are distinct and are not labeled as bestseller feeds."
                ),
            },
        }

    if mode == "fixture":
        records = [dict(row) for row in _fixture_rows(observed_at=observed_at)[:bounded]]
        for record in records:
            record["live_validated"] = False
            record["network_calls"] = False
            record["evidence_mode"] = "fixture"
            record["source"] = FIXTURE_SOURCE
            record["authenticity"] = "synthetic_or_unverified_fixture"
            for forbidden in _STRIPPED_AUTHORITY_FIELDS:
                record.pop(forbidden, None)
        return {
            "status": "fixture",
            "evidence_mode": "fixture",
            "records": records,
            "record_count": len(records),
            "readiness": readiness,
            "warnings": warnings + ["explicit_fixture_mode_not_operational_research"],
            "blockers": [],
            "capability_decision": dict(CAPABILITY_DECISION),
            "html_scraping": False,
            "network_calls": False,
            "mutated": False,
            "live_validated": False,
            "read_only": True,
            "observed_at": observed_at,
        }

    if mode == "manual_import":
        if not manual_rows:
            return {
                "status": "missing_manual_rows",
                "evidence_mode": "manual_import",
                "records": [],
                "record_count": 0,
                "readiness": readiness,
                "warnings": warnings + ["manual_rows_required"],
                "blockers": ["manual_rows_missing"],
                "capability_decision": dict(CAPABILITY_DECISION),
                "html_scraping": False,
                "network_calls": False,
                "mutated": False,
                "live_validated": False,
                "read_only": True,
                "observed_at": observed_at,
            }
        records = []
        for raw in manual_rows[:bounded]:
            if not isinstance(raw, Mapping):
                warnings.append("manual_row_skipped_non_object")
                continue
            try:
                normalized = normalize_rank_record(
                    raw, evidence_mode="manual_import", observed_at=observed_at
                )
            except ValueError:
                warnings.append("manual_row_rejected")
                continue
            if normalized is None:
                warnings.append("manual_row_missing_or_invalid_fields")
                continue
            records.append(normalized)
        return {
            "status": "manual_import" if records else "no_results",
            "evidence_mode": "manual_import",
            "records": records,
            "record_count": len(records),
            "readiness": readiness,
            "warnings": sorted(set(warnings + ["explicit_manual_import_not_live_amazon"])),
            "blockers": [],
            "capability_decision": dict(CAPABILITY_DECISION),
            "html_scraping": False,
            "network_calls": False,
            "mutated": False,
            "live_validated": False,
            "read_only": True,
            "observed_at": observed_at,
        }

    if mode == "live":
        # Category-bestseller live discovery remains unavailable even when flags
        # are set. Offline transport only exercises normalization contracts.
        if readiness["status"] != "offline_transport_contract_ready":
            return {
                "status": "blocked",
                "evidence_mode": "blocked",
                "records": [],
                "record_count": 0,
                "readiness": readiness,
                "warnings": warnings + ["live_category_bestseller_browse_unavailable"],
                "blockers": list(readiness.get("blockers") or []),
                "capability_decision": dict(CAPABILITY_DECISION),
                "html_scraping": False,
                "network_calls": False,
                "mutated": False,
                "live_validated": False,
                "read_only": True,
                "observed_at": observed_at,
            }
        try:
            payload = transport.fetch_catalog_ranks(limit=bounded)
        except Exception as exc:  # noqa: BLE001 - transport boundary is fail-soft
            return {
                "status": "transport_failed",
                "evidence_mode": "offline_transport",
                "records": [],
                "record_count": 0,
                "readiness": readiness,
                "warnings": warnings + [f"transport_failed:{type(exc).__name__}"],
                "blockers": [],
                "capability_decision": dict(CAPABILITY_DECISION),
                "html_scraping": False,
                "network_calls": False,
                "mutated": False,
                "live_validated": False,
                "read_only": True,
                "observed_at": observed_at,
            }
        if not isinstance(payload, Mapping):
            return {
                "status": "transport_invalid",
                "evidence_mode": "offline_transport",
                "records": [],
                "record_count": 0,
                "readiness": readiness,
                "warnings": warnings + ["transport_payload_not_object"],
                "blockers": [],
                "capability_decision": dict(CAPABILITY_DECISION),
                "html_scraping": False,
                "network_calls": False,
                "mutated": False,
                "live_validated": False,
                "read_only": True,
                "observed_at": observed_at,
            }
        raw_items = payload.get("items")
        if raw_items is None:
            raw_items = payload.get("data")
        if not isinstance(raw_items, list):
            return {
                "status": "transport_invalid",
                "evidence_mode": "offline_transport",
                "records": [],
                "record_count": 0,
                "readiness": readiness,
                "warnings": warnings + ["transport_items_missing"],
                "blockers": [],
                "capability_decision": dict(CAPABILITY_DECISION),
                "html_scraping": False,
                "network_calls": False,
                "mutated": False,
                "live_validated": False,
                "read_only": True,
                "observed_at": observed_at,
            }
        records = []
        for raw in raw_items[:bounded]:
            if not isinstance(raw, Mapping):
                warnings.append("transport_row_skipped_non_object")
                continue
            normalized = normalize_rank_record(
                raw, evidence_mode="offline_transport", observed_at=observed_at
            )
            if normalized is None:
                warnings.append("transport_row_missing_or_invalid_fields")
                continue
            records.append(normalized)
        return {
            "status": "offline_transport" if records else "no_results",
            "evidence_mode": "offline_transport",
            "records": records,
            "record_count": len(records),
            "readiness": readiness,
            "warnings": sorted(
                set(
                    warnings
                    + [
                        "offline_transport_is_contract_test_not_live_bestseller_discovery",
                        "do_not_label_as_category_bestseller_feed",
                    ]
                )
            ),
            "blockers": [],
            "capability_decision": dict(CAPABILITY_DECISION),
            "html_scraping": False,
            "network_calls": False,
            "mutated": False,
            "live_validated": False,
            "read_only": True,
            "observed_at": observed_at,
        }

    return {
        "status": "invalid_mode",
        "evidence_mode": "blocked",
        "records": [],
        "record_count": 0,
        "readiness": readiness,
        "warnings": warnings + ["mode_must_be_unavailable_fixture_manual_import_or_live"],
        "blockers": ["invalid_mode"],
        "capability_decision": dict(CAPABILITY_DECISION),
        "html_scraping": False,
        "network_calls": False,
        "mutated": False,
        "live_validated": False,
        "read_only": True,
        "observed_at": observed_at,
    }


def fetch() -> list[dict[str, Any]]:
    """SignalEngine path: empty list; category-bestseller discovery unavailable.

    Never scrapes Amazon HTML, never emits fixture product scores, and never
    upgrades fixtures to observed/live — including when ``DEMO_FLAG`` is set.
    Explicit demos must call ``collect_amazon_bestseller_evidence(mode="fixture")``.
    """
    global _CACHE, _CACHE_TS, _LAST_FETCH_STATUS
    if _CACHE_TS and (time.time() - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    _CACHE = []
    _CACHE_TS = time.time()
    _LAST_FETCH_STATUS = {
        "status": "unavailable",
        "reason_code": CAPABILITY_DECISION["reason_code"],
        "live_validated": False,
        "network_calls": False,
        "html_scraping": False,
        "records_returned": 0,
        "capability_decision": dict(CAPABILITY_DECISION),
    }
    _log.info(
        "amazon_bestsellers fetch unavailable_no_category_bestseller_api "
        "records=0 categories_configured=%s",
        len([c for c in _CATEGORIES if c.strip()]),
    )
    return _CACHE


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance.

    ``fetch`` returns ``[]`` so unavailable Amazon discovery cannot enter rankings.
    """
    signal_engine.register_source("amazon_bestsellers", fetch)
    try:
        from backend.discovery.registry import discovery_registry

        discovery_registry.register(
            "amazon_bestsellers",
            credential_env_vars=[],
            requires_auth=False,
        )
    except Exception:
        pass
    _log.info(
        "amazon_bestsellers adapter registered "
        "(operational unavailable; fixtures only via explicit collect mode)"
    )


# Backward-compatible private names referenced by older tests.
_MOCK_PRODUCTS = [
    {
        "product": item["product"],
        "category": item["category"],
        "rank": item["rank"],
        "score": _rank_score(item["rank"]),
    }
    for item in _FIXTURE_PRODUCTS
]


__all__ = [
    "CAPABILITY_DECISION",
    "DEMO_FLAG",
    "FIXTURE_SOURCE",
    "LIVE_FLAG",
    "LIVE_PREREQUISITES",
    "MANUAL_SOURCE",
    "OFFICIAL_REFERENCES",
    "OFFLINE_TRANSPORT_SOURCE",
    "SOURCE",
    "collect_amazon_bestseller_evidence",
    "explain_amazon_bestsellers_readiness",
    "fetch",
    "last_fetch_status",
    "normalize_rank_record",
    "register",
]
