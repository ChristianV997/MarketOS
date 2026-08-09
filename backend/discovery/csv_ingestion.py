from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Callable

from .evidence_source_contract import EvidenceRecord

MAX_ROWS = 10_000
SUPPORTED_PARSERS = {"google_trends_csv", "tiktok_creative_center_csv", "amazon_bestsellers_csv", "meta_ad_library_csv", "reddit_keyword_csv", "mercadolibre_snapshot_csv", "supplier_catalog_csv", "shopify_orders_csv", "stripe_payments_csv", "generic_market_csv", "local_json_dataset"}
KNOWN_SIGNALS = {"trend_proxy", "demand_proxy", "competition_proxy", "margin_proxy", "audience_proxy", "creative_proxy", "pain_point", "price_signal", "supplier_proxy", "risk_proxy", "own_store_sales_proxy", "rank_proxy"}


def _project_root() -> Path:
    return Path.cwd().resolve()


def _safe_path(path: str) -> Path:
    candidate = Path(path)
    if ".." in candidate.parts:
        raise ValueError("import_path_traversal_blocked")
    resolved = candidate.resolve()
    root = _project_root()
    allowed = [root, root / "data", root / "datasets", root / "fixtures", root / "tests"]
    if not any(resolved == item or item in resolved.parents for item in allowed):
        raise ValueError("import_path_outside_project_roots")
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def load_csv_rows(path: str, max_rows: int = MAX_ROWS) -> list[dict[str, str]]:
    if max_rows < 1 or max_rows > MAX_ROWS:
        raise ValueError("row_limit_invalid")
    candidate = _safe_path(path)
    try:
        # utf-8-sig accepts ordinary UTF-8 and strips a BOM when present.
        text = candidate.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = candidate.read_text(encoding="utf-8")
    return [dict(row) for _, row in zip(range(max_rows), csv.DictReader(text.splitlines()))]


def _text(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = str(row.get(name, "") or "").strip()
        if value:
            return value
    return ""


def _number(row: dict[str, str], *names: str) -> float | None:
    raw = _text(row, *names).replace(",", "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _record(row: dict[str, str], index: int, parser: str, provenance: dict[str, Any], entity_type: str, entity_name: str, signal: str, value: Any, metadata: dict[str, Any] | None = None) -> EvidenceRecord | None:
    if not entity_name or signal not in KNOWN_SIGNALS:
        return None
    row_provenance = dict(provenance or {})
    row_provenance.update({"parser_type": parser, "row_number": index + 2, "source_name": row_provenance.get("source_name", "local_import")})
    seed = f"{row_provenance.get('source_name')}:{parser}:{index}:{entity_type}:{entity_name.lower()}:{signal}"
    import hashlib
    return EvidenceRecord(f"evidence_{hashlib.sha256(seed.encode()).hexdigest()[:16]}", str(row_provenance.get("source_name", "local_import")), "local_file", entity_type, entity_name, signal, value, 1.0, 0.5, 0.0, row_provenance, metadata or {})


def _parse(rows: list[dict[str, str]], parser: str, provenance: dict[str, Any], builder: Callable[[dict[str, str]], list[tuple[str, str, Any, dict[str, Any]]]]) -> list[EvidenceRecord]:
    output: list[EvidenceRecord] = []
    for index, row in enumerate(rows):
        for entity_type, signal, value, metadata in builder(row):
            record = _record(row, index, parser, provenance, entity_type, _text(row, "category", "product", "keyword", "search_term", "entity_name", "subreddit"), signal, value, metadata)
            if record: output.append(record)
    return output


def parse_google_trends_csv(rows, provenance):
    return _parse(rows, "google_trends_csv", provenance, lambda r: [("category", "trend_proxy", _number(r, "trend_score", "growth") or 0, {})] if _text(r, "category", "keyword", "search_term") else [])


def parse_tiktok_creative_center_csv(rows, provenance):
    def build(r):
        result = [("product_theme", "creative_proxy", _number(r, "views", "likes", "ctr", "cvr") or 0, {})]
        if _number(r, "views", "likes"): result.append(("product_theme", "trend_proxy", _number(r, "views", "likes") or 0, {}))
        if _number(r, "ad_count", "spend"): result.append(("product_theme", "competition_proxy", _number(r, "ad_count", "spend") or 0, {}))
        return result
    return _parse(rows, "tiktok_creative_center_csv", provenance, build)


def parse_amazon_bestsellers_csv(rows, provenance):
    def build(r):
        result = [("product", "competition_proxy", _number(r, "review_count", "rating") or 0, {})]
        if _number(r, "rank") is not None: result.append(("product", "demand_proxy", 1.0 / max(_number(r, "rank") or 1, 1), {"proxy": "rank_proxy"}))
        if _number(r, "price") is not None: result.append(("product", "price_signal", _number(r, "price"), {}))
        return result
    return _parse(rows, "amazon_bestsellers_csv", provenance, build)


def parse_meta_ad_library_csv(rows, provenance):
    return _parse(rows, "meta_ad_library_csv", provenance, lambda r: [("product_theme", "competition_proxy", _number(r, "ad_count", "active_days") or 0, {}), ("product_theme", "creative_proxy", _number(r, "active_days") or 0, {})])


def parse_reddit_keyword_csv(rows, provenance):
    def build(r):
        result = [("audience", "audience_proxy", _number(r, "mentions", "upvotes", "comments") or 0, {}), ("pain_point", "pain_point", _text(r, "pain_point", "keyword"), {})]
        if _number(r, "growth", "time_window_growth") is not None: result.append(("audience", "trend_proxy", _number(r, "growth", "time_window_growth") or 0, {}))
        return result
    return _parse(rows, "reddit_keyword_csv", provenance, build)


def parse_mercadolibre_snapshot_csv(rows, provenance):
    def build(r):
        result = [("product", "price_signal", _number(r, "price") or 0, {}), ("product", "competition_proxy", _number(r, "seller_count", "reviews") or 0, {})]
        if _number(r, "sold_count") is not None: result.append(("product", "demand_proxy", _number(r, "sold_count") or 0, {"explicit_field": "sold_count"}))
        return result
    return _parse(rows, "mercadolibre_snapshot_csv", provenance, build)


def parse_supplier_catalog_csv(rows, provenance):
    def build(r):
        cost, shipping = _number(r, "supplier_cost"), _number(r, "shipping_cost")
        result = []
        if cost is not None: result.append(("product", "margin_proxy", cost, {"supplier_cost": cost, "shipping_cost": shipping}))
        result.append(("product", "supplier_proxy", _number(r, "availability") if _number(r, "availability") is not None else 0.5, {"supplier": _text(r, "supplier")}))
        if _number(r, "moq") is not None and (_number(r, "moq") or 0) > 100: result.append(("product", "risk_proxy", 1.0, {"risk": "high_moq"}))
        if _number(r, "lead_time_days") is not None and (_number(r, "lead_time_days") or 0) > 30: result.append(("product", "risk_proxy", 1.0, {"risk": "long_lead_time"}))
        return result
    return _parse(rows, "supplier_catalog_csv", provenance, build)


def parse_shopify_orders_csv(rows, provenance):
    def build(r):
        result = [("product", "own_store_sales_proxy", _number(r, "net_sales", "gross_sales", "quantity") or 0, {"first_party": True})]
        if _number(r, "net_sales", "gross_sales") is not None: result.append(("product", "price_signal", _number(r, "net_sales", "gross_sales") or 0, {}))
        if _number(r, "refunds") is not None and (_number(r, "refunds") or 0) > 0: result.append(("product", "risk_proxy", _number(r, "refunds") or 0, {"risk": "refunds"}))
        return result
    return _parse(rows, "shopify_orders_csv", provenance, build)


def parse_stripe_payments_csv(rows, provenance):
    def build(r):
        result = [("product", "own_store_sales_proxy", _number(r, "amount") or 0, {"first_party": True, "currency": _text(r, "currency")})]
        if _number(r, "amount") is not None: result.append(("product", "price_signal", _number(r, "amount") or 0, {}))
        if _text(r, "refunded", "status").lower() in {"true", "refunded", "failed"}: result.append(("product", "risk_proxy", 1.0, {"risk": _text(r, "status", "refunded")}))
        return result
    return _parse(rows, "stripe_payments_csv", provenance, build)


def parse_generic_market_csv(rows, provenance):
    def build(r):
        signal = _text(r, "signal_type")
        if signal not in KNOWN_SIGNALS: return []
        raw = _text(r, "value")
        value: Any = raw
        try: value = float(raw)
        except ValueError: pass
        metadata: dict[str, Any] = {}
        if _text(r, "metadata_json"):
            try: metadata = json.loads(_text(r, "metadata_json"))
            except json.JSONDecodeError: metadata = {"metadata_json_invalid": True}
        return [(_text(r, "entity_type") or "category", signal, value, metadata)]
    return _parse(rows, "generic_market_csv", provenance, build)


PARSERS = {name: globals()[f"parse_{name.removesuffix('_csv')}_csv"] for name in []}
PARSERS = {"google_trends_csv": parse_google_trends_csv, "tiktok_creative_center_csv": parse_tiktok_creative_center_csv, "amazon_bestsellers_csv": parse_amazon_bestsellers_csv, "meta_ad_library_csv": parse_meta_ad_library_csv, "reddit_keyword_csv": parse_reddit_keyword_csv, "mercadolibre_snapshot_csv": parse_mercadolibre_snapshot_csv, "supplier_catalog_csv": parse_supplier_catalog_csv, "shopify_orders_csv": parse_shopify_orders_csv, "stripe_payments_csv": parse_stripe_payments_csv, "generic_market_csv": parse_generic_market_csv}
