"""Offline marketplace-trend import adapters.

The adapters accept sanitized JSON snapshots and seller-provided CSV exports. They
do not fetch marketplace pages, accept credentials, persist HTML, or pass through
provider payloads. A future public-page adapter can be added behind a separate
explicit network gate without changing this normalization contract.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from evaluation.commerce.marketplace_trends import (
    PROVENANCE,
    SOURCE_TYPES,
    SUPPORTED,
    MarketplaceTrendEvidence,
    collapse_duplicates,
)

SECRET_KEY = re.compile(r"(token|secret|password|api[_-]?key|authorization|cookie|private[_-]?key)", re.I)
SECRET_VALUE = re.compile(r"(bearer\s+|sk_live_|sk_test_|ghp_|xox[baprs]-|-----BEGIN)", re.I)

SOURCE_DEFAULTS = {
    "amazon": "amazon_best_sellers_snapshot",
    "ebay": "ebay_public_listing_snapshot",
    "mercadolibre": "mercadolibre_trends_snapshot",
    "alibaba": "alibaba_market_trending_snapshot",
    "aliexpress": "aliexpress_trending_snapshot",
    "etsy": "etsy_public_listing_snapshot",
    "walmart": "walmart_public_listing_snapshot",
    "shopify": "shopify_storefront_snapshot",
    "woocommerce": "woocommerce_storefront_snapshot",
}


class MarketplaceImportError(ValueError):
    """Raised when a local import would violate the sanitized input contract."""


def validate_input_path(path: str | Path) -> Path:
    """Reject traversal attempts while allowing explicit local fixture paths."""
    candidate = Path(path)
    if ".." in candidate.parts:
        raise MarketplaceImportError("path traversal is not allowed")
    if candidate.suffix.lower() not in {".json", ".csv"}:
        raise MarketplaceImportError("only sanitized JSON and CSV inputs are supported")
    if not candidate.is_file():
        raise MarketplaceImportError("marketplace import file does not exist")
    return candidate


def _contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(SECRET_KEY.search(str(key)) or _contains_secret(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(item) for item in value)
    return bool(SECRET_VALUE.search(str(value))) if value is not None else False


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items() if not SECRET_KEY.search(str(key))}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).replace(",", "")
    text = re.sub(r"[^0-9.\-]", " ", text).strip()
    try:
        return float(text.split()[0])
    except (IndexError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "best seller", "bestseller"}


def _row_value(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _provenance(row: Mapping[str, Any], mode: str) -> dict[str, str]:
    raw = row.get("field_provenance")
    if isinstance(raw, Mapping):
        result = {
            str(key): (str(value) if str(value) in PROVENANCE else "malformed")
            for key, value in raw.items()
        }
    else:
        result = {}
    for field in (
        "rank_position",
        "best_seller_badge",
        "trend_label",
        "search_growth_signal",
        "sold_count_text",
        "review_count",
        "rating",
        "price",
        "price_band_min",
        "price_band_max",
        "offer_count",
        "seller_count",
        "availability",
        "shipping_signal",
        "fulfillment_signal",
    ):
        if field not in result and row.get(field) not in (None, ""):
            result[field] = "manual_import" if mode == "manual_import" else "fixture"
    return result


def normalize_record(
    row: Mapping[str, Any],
    *,
    default_marketplace: str = "amazon",
    default_source_type: str | None = None,
    mode: str = "fixture",
) -> MarketplaceTrendEvidence | None:
    """Normalize one sanitized row; malformed rows return ``None`` safely."""
    if not isinstance(row, Mapping) or _contains_secret(row):
        return None
    row = _clean(row)
    marketplace = str(_row_value(row, "marketplace", "source_marketplace") or default_marketplace).lower()
    if marketplace not in SUPPORTED:
        return None
    source_type = str(_row_value(row, "source_type") or default_source_type or SOURCE_DEFAULTS[marketplace])
    if source_type not in SOURCE_TYPES:
        source_type = default_source_type or SOURCE_DEFAULTS[marketplace]
    candidate_id = str(_row_value(row, "candidate_id", "product_id", "item_id", "asin", "sku") or "").strip()
    if not candidate_id:
        return None
    nested = row.get("product") if isinstance(row.get("product"), Mapping) else {}
    merged = {**nested, **row}
    provenance = _provenance(merged, mode)
    warnings = [str(item) for item in merged.get("warnings", []) if isinstance(item, str)]
    if not merged.get("price") and not merged.get("price_band_min"):
        warnings.append("price_unavailable")
    return MarketplaceTrendEvidence(
        candidate_id=candidate_id,
        query=str(_row_value(merged, "query", "title", "product_title") or candidate_id),
        marketplace=marketplace,
        source_type=source_type,
        site_id=str(_row_value(merged, "site_id") or ""),
        category_id=str(_row_value(merged, "category_id") or ""),
        source_url=str(_row_value(merged, "source_url", "url", "product_url") or ""),
        evidence_mode=mode,
        rank_position=_integer(_row_value(merged, "rank_position", "rank")),
        best_seller_badge=_bool(_row_value(merged, "best_seller_badge", "badge", "best_seller")),
        trend_label=str(_row_value(merged, "trend_label", "trend") or ""),
        search_growth_signal=_number(_row_value(merged, "search_growth_signal", "growth_signal", "search_growth")),
        sold_count_text=str(_row_value(merged, "sold_count_text", "sold_count", "units_sold") or ""),
        review_count=_integer(_row_value(merged, "review_count", "reviews")),
        rating=_number(_row_value(merged, "rating", "stars")),
        price=_number(_row_value(merged, "price", "current_price", "sale_price")),
        currency=str(_row_value(merged, "currency", "price_currency") or "USD").upper(),
        price_band_min=_number(_row_value(merged, "price_band_min", "min_price")),
        price_band_max=_number(_row_value(merged, "price_band_max", "max_price")),
        offer_count=_integer(_row_value(merged, "offer_count", "offers")),
        seller_count=_integer(_row_value(merged, "seller_count", "sellers")),
        availability=str(_row_value(merged, "availability", "stock_status") or ""),
        shipping_signal=str(_row_value(merged, "shipping_signal", "shipping") or ""),
        fulfillment_signal=str(_row_value(merged, "fulfillment_signal", "fulfillment") or ""),
        source_confidence=max(0.0, min(1.0, _number(_row_value(merged, "source_confidence", "confidence")) or (0.65 if mode == "manual_import" else 0.55))),
        field_provenance=provenance,
        warnings=tuple(sorted(set(warnings))),
        observed_at=str(_row_value(merged, "observed_at", "captured_at") or "deterministic"),
    )


def _json_rows(path: str | Path) -> list[Mapping[str, Any]]:
    target = validate_input_path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, Mapping)]
    if isinstance(raw, Mapping):
        for key in ("records", "items", "products", "results", "offers"):
            if isinstance(raw.get(key), list):
                return [item for item in raw[key] if isinstance(item, Mapping)]
        return [raw]
    return []


def import_json(
    path: str | Path,
    *,
    marketplace: str = "amazon",
    source_type: str | None = None,
) -> list[MarketplaceTrendEvidence]:
    rows = _json_rows(path)
    return collapse_duplicates(
        item
        for row in rows
        if (item := normalize_record(row, default_marketplace=marketplace, default_source_type=source_type, mode="fixture"))
    )


def import_csv(path: str | Path, *, marketplace: str | None = None) -> list[MarketplaceTrendEvidence]:
    target = validate_input_path(path)
    with target.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return collapse_duplicates(
        item
        for row in rows
        if (item := normalize_record(row, default_marketplace=marketplace or str(row.get("marketplace") or "ebay"), default_source_type="manual_csv_import", mode="manual_import"))
    )


def import_marketplace_json(path: str | Path, marketplace: str, source_type: str) -> list[MarketplaceTrendEvidence]:
    return import_json(path, marketplace=marketplace, source_type=source_type)


def import_amazon_best_sellers(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "amazon", "amazon_best_sellers_snapshot")


def import_amazon_product(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "amazon", "amazon_product_snapshot")


def import_ebay_terapeak(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_csv(path, marketplace="ebay")


def import_mercadolibre_trends(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "mercadolibre", "mercadolibre_trends_snapshot")


def import_mercadolibre_highlights(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "mercadolibre", "mercadolibre_highlights_snapshot")


def import_mercadolibre_best_sellers(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "mercadolibre", "mercadolibre_best_sellers_snapshot")


def import_alibaba_trending(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "alibaba", "alibaba_market_trending_snapshot")


def import_alibaba_high_profit(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "alibaba", "alibaba_high_profit_snapshot")


def import_aliexpress_trending(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "aliexpress", "aliexpress_trending_snapshot")


def import_etsy_listing(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "etsy", "etsy_public_listing_snapshot")


def import_walmart_listing(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "walmart", "walmart_public_listing_snapshot")


def import_shopify_storefront(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "shopify", "shopify_storefront_snapshot")


def import_woocommerce_storefront(path: str | Path) -> list[MarketplaceTrendEvidence]:
    return import_marketplace_json(path, "woocommerce", "woocommerce_storefront_snapshot")
