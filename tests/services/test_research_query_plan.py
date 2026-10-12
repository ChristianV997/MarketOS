"""Synthetic tests for offline localized research query planning."""
from __future__ import annotations

import json

import pytest

from services.research_query_plan import (
    MAX_QUERIES_PER_SOURCE,
    MAX_TOTAL_QUERIES,
    SOURCE_FAMILIES,
    ProductResearchBrief,
    build_research_query_plan,
)


def _brief(**overrides):
    base = {
        "product_query": "portable blender",
        "category": "kitchen appliances",
        "region": "MX",
        "language": "es",
        "intended_buyer": "consumer",
    }
    base.update(overrides)
    return ProductResearchBrief(**base)


def test_english_us_plan_keeps_source_families_distinct_and_bounded():
    plan = build_research_query_plan(
        _brief(language="en", region="US", intended_buyer="business")
    )
    assert plan.ok
    families = {item.source_family for item in plan.queries}
    assert families == set(SOURCE_FAMILIES)
    for family in SOURCE_FAMILIES:
        family_queries = [q for q in plan.queries if q.source_family == family]
        assert 1 <= len(family_queries) <= MAX_QUERIES_PER_SOURCE
        assert family_queries[0].query_text == "portable blender"
        assert family_queries[0].is_original is True
    assert len(plan.queries) <= MAX_TOTAL_QUERIES
    supplier = [q.query_text.lower() for q in plan.queries if q.source_family == "supplier"]
    marketplace = [q.query_text.lower() for q in plan.queries if q.source_family == "marketplace"]
    attention = [q.query_text.lower() for q in plan.queries if q.source_family == "consumer_attention"]
    assert any("wholesale" in text or "moq" in text or "supplier" in text for text in supplier)
    assert not any("wholesale" in text or "moq" in text for text in marketplace)
    assert any("review" in text or "trend" in text or "demand" in text for text in attention)
    assert plan.queries[0].rationale
    assert "not evidence" in " ".join(plan.limitations).lower() or any(
        "not evidence" in q.rationale.lower() for q in plan.queries[:1]
    )
    assert plan.launch_authorized is False
    assert plan.live_validated is False


def test_spanish_mexico_consumer_plan_uses_bounded_local_terms():
    plan = build_research_query_plan(_brief())
    assert plan.ok
    texts = " ".join(q.query_text.lower() for q in plan.queries)
    assert "licuadora" in texts or "portable blender" in texts
    assert "méxico" in texts or "mexico" in texts
    supplier = " ".join(q.query_text.lower() for q in plan.queries if q.source_family == "supplier")
    assert "proveedor" in supplier or "mayoreo" in supplier
    attention = " ".join(
        q.query_text.lower() for q in plan.queries if q.source_family == "consumer_attention"
    )
    assert "reseña" in attention or "opiniones" in attention or "tendencia" in attention
    marketplace = [
        q for q in plan.queries if q.source_family == "marketplace" and not q.is_original
    ]
    assert marketplace
    assert all(q.is_evidence is False for q in plan.queries)


def test_preserves_original_query_and_flags_ambiguous_brief():
    plan = build_research_query_plan(
        _brief(product_query="it", category="", region="MX", language="es")
    )
    assert plan.ok is False or "ambiguous_brief" in plan.flags
    assert "ambiguous_brief" in plan.flags
    originals = [q for q in plan.queries if q.is_original]
    assert originals
    assert all(q.query_text == "it" for q in originals)
    assert plan.brief.product_query == "it"


def test_unsupported_language_does_not_invent_translations():
    plan = build_research_query_plan(_brief(language="ja", region="JP"))
    assert "unsupported_language" in plan.flags
    # Only originals (or region-tagged originals) — no Japanese invention
    for item in plan.queries:
        assert "ポータブル" not in item.query_text
        assert item.language_applied in {"ja", "unsupported"}
    assert any(q.is_original for q in plan.queries)


def test_deterministic_ordering_across_runs():
    first = build_research_query_plan(_brief()).to_dict()
    second = build_research_query_plan(_brief()).to_dict()
    assert first == second
    families = [q["source_family"] for q in first["queries"]]
    assert families == sorted(families, key=lambda name: SOURCE_FAMILIES.index(name))


def test_buyer_intent_changes_variants_without_crossing_families():
    consumer = build_research_query_plan(_brief(intended_buyer="consumer", language="en", region="US"))
    reseller = build_research_query_plan(_brief(intended_buyer="reseller", language="en", region="US"))
    consumer_supplier = {
        q.query_text for q in consumer.queries if q.source_family == "supplier" and not q.is_original
    }
    reseller_supplier = {
        q.query_text for q in reseller.queries if q.source_family == "supplier" and not q.is_original
    }
    assert consumer_supplier != reseller_supplier
    assert any("dropship" in text.lower() or "reseller" in text.lower() for text in reseller_supplier)
    attention_reseller = [
        q.query_text.lower() for q in reseller.queries if q.source_family == "consumer_attention"
    ]
    assert not any("moq" in text for text in attention_reseller)


def test_category_terms_expand_only_from_bounded_lexicon():
    plan = build_research_query_plan(
        _brief(
            product_query="yoga mat",
            category="fitness",
            language="es",
            region="MX",
            intended_buyer="consumer",
        )
    )
    texts = " ".join(q.query_text.lower() for q in plan.queries)
    assert "colchoneta" in texts or "yoga" in texts
    # Must not invent attributes absent from brief/lexicon
    assert "eco-friendly" not in texts
    assert "waterproof" not in texts


def test_query_count_bounds_hard_cap():
    plan = build_research_query_plan(
        _brief(
            product_query="stainless steel water bottle",
            category="drinkware",
            language="en",
            region="US",
            intended_buyer="reseller",
        )
    )
    assert len(plan.queries) <= MAX_TOTAL_QUERIES
    for family in SOURCE_FAMILIES:
        assert len([q for q in plan.queries if q.source_family == family]) <= MAX_QUERIES_PER_SOURCE


def test_serialization_is_json_safe_and_explicitly_non_authoritative():
    plan = build_research_query_plan(_brief())
    payload = plan.to_dict()
    json.dumps(payload)
    assert payload["plan_version"] == "research-query-plan-v1"
    assert payload["live_validated"] is False
    assert payload["launch_authorized"] is False
    assert payload["authority"] == "query_planning_only"
    assert all(item["is_evidence"] is False for item in payload["queries"])


def test_rejects_secret_shaped_brief_without_echoing_secret():
    with pytest.raises(ValueError, match="prohibited_or_secret_shaped"):
        build_research_query_plan(_brief(product_query="blender sk-live-abcdefghijklmnopqrstuv"))
