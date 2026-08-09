from __future__ import annotations

from typing import Any

from .evidence_import import EvidenceSourceQuality


_BASE: dict[str, dict[str, Any]] = {
    "google_trends_csv": {"score": 62, "allowed": ["trend_proxy", "audience_proxy"], "blocked": ["profit_proxy", "roas_proxy"], "strengths": ["trend direction proxy"], "weaknesses": ["not conversion or profit evidence"]},
    "tiktok_creative_center_csv": {"score": 60, "allowed": ["creative_proxy", "trend_proxy", "competition_proxy"], "blocked": ["profit_proxy", "demand_actual"], "strengths": ["creative and short-term trend signals"], "weaknesses": ["durable demand and profitability are unproven"]},
    "amazon_bestsellers_csv": {"score": 64, "allowed": ["competition_proxy", "demand_proxy", "price_signal"], "blocked": ["profit_proxy"], "strengths": ["price and rank proxies"], "weaknesses": ["rank is not exact sales"]},
    "meta_ad_library_csv": {"score": 58, "allowed": ["competition_proxy", "creative_proxy"], "blocked": ["profit_proxy", "demand_actual"], "strengths": ["observed creative and advertiser activity"], "weaknesses": ["no reliable profitability evidence"]},
    "reddit_keyword_csv": {"score": 50, "allowed": ["audience_proxy", "pain_point", "trend_proxy"], "blocked": ["market_size_actual", "profit_proxy"], "strengths": ["audience language and pain points"], "weaknesses": ["self-selected, non-representative audience"]},
    "mercadolibre_snapshot_csv": {"score": 65, "allowed": ["price_signal", "competition_proxy", "demand_proxy"], "blocked": ["profit_proxy"], "strengths": ["marketplace price and seller proxies"], "weaknesses": ["snapshot is not a full market census"]},
    "supplier_catalog_csv": {"score": 55, "allowed": ["margin_proxy", "supplier_proxy", "risk_proxy", "price_signal"], "blocked": ["demand_proxy", "profit_proxy"], "strengths": ["cost, availability, and lead-time inputs"], "weaknesses": ["supplier catalog does not prove demand"]},
    "shopify_orders_csv": {"score": 88, "allowed": ["own_store_sales_proxy", "price_signal", "risk_proxy"], "blocked": ["demand_proxy", "market_size_actual"], "strengths": ["first-party historical store facts"], "weaknesses": ["only represents the owner’s store"]},
    "stripe_payments_csv": {"score": 90, "allowed": ["own_store_sales_proxy", "price_signal", "risk_proxy"], "blocked": ["demand_proxy", "market_size_actual"], "strengths": ["first-party payment outcomes"], "weaknesses": ["payment history is not general market demand"]},
    "generic_market_csv": {"score": 35, "allowed": ["trend_proxy", "demand_proxy", "competition_proxy", "margin_proxy", "audience_proxy", "creative_proxy", "pain_point", "price_signal", "supplier_proxy", "risk_proxy", "own_store_sales_proxy"], "blocked": ["profit_proxy", "roas_proxy"], "strengths": ["flexible user-provided evidence"], "weaknesses": ["quality depends on documentation and provenance"]},
    "local_json_dataset": {"score": 35, "allowed": ["trend_proxy", "demand_proxy", "competition_proxy", "margin_proxy", "audience_proxy", "creative_proxy", "pain_point", "price_signal", "supplier_proxy", "risk_proxy"], "blocked": ["profit_proxy", "roas_proxy"], "strengths": ["repeatable local input"], "weaknesses": ["not live unless separately documented"]},
}


def score_source_quality(source_name: str, source_type: str, parser_type: str, provenance: dict[str, Any], row_count: int, fields_present: list[str]) -> EvidenceSourceQuality:
    spec = _BASE.get(parser_type, _BASE["generic_market_csv"])
    synthetic = provenance.get("type") == "synthetic_fixture" or provenance.get("not_real_market_data") is True
    score = 15.0 if synthetic else float(spec["score"])
    strengths = list(spec["strengths"])
    weaknesses = list(spec["weaknesses"])
    if not provenance:
        score = 0.0
        weaknesses.append("provenance missing")
    if row_count <= 0:
        score -= 10
        weaknesses.append("empty import")
    if len(fields_present) < 2:
        score -= 10
        weaknesses.append("sparse fields")
    if synthetic:
        weaknesses.append("synthetic fixture; not real market data")
    score = max(0.0, min(score, 100.0))
    return EvidenceSourceQuality(source_name, source_type, score, score / 100.0, strengths, list(dict.fromkeys(weaknesses)), list(spec["allowed"]), list(spec["blocked"]), "static_local_export", ["source_file", "parser_type", "row_number", "source_name"], {"parser_type": parser_type, "row_count": row_count, "fields_present": sorted(set(fields_present)), "synthetic_or_cached_only": synthetic})
