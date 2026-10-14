"""Amazon bestseller research signal adapter (fixture-first, scrape-disabled).

Historical behavior scraped Amazon Best Sellers HTML and fell back to mock
rows. That scrape path is removed. Default ``fetch()`` returns an empty list so
SignalEngine never receives fixture product scores. Offline fixture/manual
rows remain available only via ``collect_amazon_bestseller_evidence()``.

Official live category-bestseller browse is not enabled here: Amazon's
documented programmatic catalog/rank access is gated (Selling Partner API
Catalog Items for sellers/vendors; Creators API for Associates). This module
exposes an injected transport seam and an explicit live gate that remains
blocked unless a caller supplies a fake/offline transport for contract tests.

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
FIXTURE_SOURCE = "amazon_bestsellers_mock"  # retained: research consumers filter this as synthetic
LIVE_FLAG = "MARKETOS_AMAZON_BESTSELLERS_LIVE"
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

_CACHE: list[dict[str, Any]] = []
_CACHE_TS: float = 0.0
_CACHE_TTL = 3600  # 1 hour

# Categories remain configuration metadata for fixture rows only (no HTTP).
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
        # Explicit zero is preserved as a numeric score of 0.0 (not missing).
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
                "rank_semantics": "relative_bestseller_rank_not_unit_sales",
                "live_validated": False,
                "network_calls": False,
                "mutated": False,
            }
        )
    return rows


def explain_amazon_bestsellers_readiness(
    environ: Mapping[str, str] | None = None,
    *,
    allow_network: bool = False,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Explain why live Amazon bestseller research is blocked by default."""
    env = os.environ if environ is None else environ
    live_flag = str(env.get(LIVE_FLAG, "0")).strip() == "1"
    provider = str(env.get(PROVIDER_ENV, "")).strip().lower()
    transport_ready = transport is not None and callable(getattr(transport, "fetch_catalog_ranks", None))
    offline = getattr(transport, "offline_fixture", False) is True if transport is not None else False
    blockers = [
        "html_bestseller_scrape_disabled",
        "no_public_ungated_bestseller_browse_api_documented",
        "sp_api_catalog_items_requires_seller_or_vendor_product_listing_role",
        "creators_api_requires_amazon_associates_enrollment_and_qualifying_sales",
        "bestseller_rank_is_relative_not_unit_sales_or_demand_proof",
    ]
    if not live_flag:
        blockers.append(f"{LIVE_FLAG}_disabled")
    if not allow_network:
        blockers.append("allow_network_false")
    if not transport_ready:
        blockers.append("injected_transport_required")
    elif not offline and live_flag and allow_network:
        blockers.append("live_provider_calls_not_enabled_in_this_lane")
    status = "fixture_only"
    if live_flag and allow_network and transport_ready and offline:
        status = "offline_transport_ready"
    elif live_flag and allow_network and transport_ready:
        status = "blocked_gated_official_access"
    return {
        "provider": provider or "unset",
        "live_flag_enabled": live_flag,
        "allow_network": bool(allow_network),
        "transport_injected": transport_ready,
        "transport_offline_fixture": offline,
        "status": status,
        "read_only": True,
        "mutated": False,
        "html_scraping": False,
        "credentials_inspected": False,
        "supported": {
            "fixture_bestseller_rows": True,
            "manual_import_normalization": True,
            "injected_offline_transport_normalization": True,
        },
        "unsupported": {
            "amazon_html_best_sellers_scrape": True,
            "ungated_live_bestseller_browse": True,
            "mock_rows_as_observed_evidence": True,
            "rank_as_unit_sales_or_profit": True,
        },
        "official_references": [
            "https://developer-docs.amazon.com/sp-api/docs/catalog-items-api",
            "https://developer-docs.amazon.com/sp-api/docs/catalog-items-api-v2022-04-01-reference",
            "https://affiliate-program.amazon.com/creatorsapi/docs/en-us/introduction",
        ],
        "blockers": blockers,
    }


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
        # Do not invent a currency for a present price.
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
    source = FIXTURE_SOURCE if evidence_mode in {"fixture", "manual_import"} else "amazon_bestsellers_offline_transport"
    score = _rank_score(rank)
    # Fixture/manual/offline rows are never live-validated. Injected True is ignored.
    # Sales-volume / demand-authority keys from raw input are never copied through.
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
        "observation_kind": "fixture_bestseller_rank" if evidence_mode == "fixture" else "manual_or_offline_rank",
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
    mode: str = "fixture",
    allow_network: bool = False,
    transport: Any | None = None,
    manual_rows: list[Mapping[str, Any]] | None = None,
    environ: Mapping[str, str] | None = None,
    clock: Callable[[], float] | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Collect Amazon bestseller-style evidence with explicit status labels.

    ``fetch()`` is the SignalEngine list API and returns ``[]`` so fixture
    scores never enter rankings. This function is the structured offline
    research entrypoint and never performs live Amazon HTTP.
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
    ]

    if mode == "fixture":
        records = [_row for _row in _fixture_rows(observed_at=observed_at)[:bounded]]
        # Hard-enforce non-live labels even if fixture builders drift.
        for record in records:
            record["live_validated"] = False
            record["evidence_mode"] = "fixture"
            record["rank_semantics"] = "relative_bestseller_rank_not_unit_sales"
            record["source"] = FIXTURE_SOURCE
            for forbidden in _STRIPPED_AUTHORITY_FIELDS:
                record.pop(forbidden, None)
        return {
            "status": "fixture",
            "evidence_mode": "fixture",
            "records": records,
            "record_count": len(records),
            "readiness": readiness,
            "warnings": warnings,
            "blockers": [],
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
            "warnings": sorted(set(warnings)),
            "blockers": [],
            "html_scraping": False,
            "network_calls": False,
            "mutated": False,
            "live_validated": False,
            "read_only": True,
            "observed_at": observed_at,
        }

    if mode == "live":
        if readiness["status"] != "offline_transport_ready":
            return {
                "status": "blocked",
                "evidence_mode": "blocked",
                "records": [],
                "record_count": 0,
                "readiness": readiness,
                "warnings": warnings + ["live_amazon_bestseller_browse_unavailable"],
                "blockers": list(readiness.get("blockers") or []),
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
            "warnings": sorted(set(warnings)),
            "blockers": [],
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
        "warnings": warnings + ["mode_must_be_fixture_manual_import_or_live"],
        "blockers": ["invalid_mode"],
        "html_scraping": False,
        "network_calls": False,
        "mutated": False,
        "live_validated": False,
        "read_only": True,
        "observed_at": observed_at,
    }


def fetch() -> list[dict[str, Any]]:
    """Return an empty list for SignalEngine (non-authoritative by default).

    Never scrapes Amazon HTML, never emits ``amazon_bestsellers_mock`` product
    score rows on the SignalEngine path, and never upgrades fixtures to
    observed/live. Offline fixture rows remain available only via
    ``collect_amazon_bestseller_evidence(mode="fixture")``. The empty result
    is cached for one hour.
    """
    global _CACHE, _CACHE_TS
    if _CACHE_TS and (time.time() - _CACHE_TS) < _CACHE_TTL:
        return _CACHE

    _CACHE = []
    _CACHE_TS = time.time()
    _log.debug(
        "amazon_bestsellers fetch empty_non_authoritative categories_configured=%s",
        len([c for c in _CATEGORIES if c.strip()]),
    )
    return _CACHE


def register(signal_engine: Any) -> None:
    """Register this adapter with the provided SignalEngine instance.

    ``fetch`` returns ``[]`` so fixture product scores cannot enter rankings.
    """
    signal_engine.register_source("amazon_bestsellers", fetch)
    try:
        from backend.discovery.registry import discovery_registry

        # Empty SignalEngine registration stays auth-optional; live SP-API /
        # Creators access is separately gated and blocked by default.
        discovery_registry.register(
            "amazon_bestsellers",
            credential_env_vars=[],
            requires_auth=False,
        )
    except Exception:
        pass
    _log.info(
        "amazon_bestsellers adapter registered "
        "(fetch empty for SignalEngine; fixtures offline via collect only)"
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
    "FIXTURE_SOURCE",
    "LIVE_FLAG",
    "SOURCE",
    "collect_amazon_bestseller_evidence",
    "explain_amazon_bestsellers_readiness",
    "fetch",
    "normalize_rank_record",
    "register",
]
