"""Deterministic offline builder for localized research query plans."""
from __future__ import annotations

import re
from typing import Any, Mapping

from .lexicon import (
    AMBIGUOUS_TOKENS,
    BUYER_MODIFIERS,
    CATEGORY_SYNONYMS,
    FAMILY_MODIFIERS,
    QUERY_LOCALIZATIONS,
    REGION_LABELS,
)
from .schemas import (
    MAX_BRIEF_CHARS,
    MAX_QUERIES_PER_SOURCE,
    MAX_TOTAL_QUERIES,
    PLAN_VERSION,
    PlannedQuery,
    ProductResearchBrief,
    ResearchQueryPlan,
    SOURCE_FAMILIES,
    SUPPORTED_LANGUAGES,
    coerce_brief,
)

_SECRET = re.compile(
    r"(?:sk-live-|sk-test-|ghp_|github_pat_|AKIA[0-9A-Z]{16}|bearer\s+[a-z0-9._-]{10,}|"
    r"-----begin |xoxb-|aiza)",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,3}$")
_WS = re.compile(r"\s+")


def _clean_text(value: str, *, limit: int = MAX_BRIEF_CHARS) -> str:
    text = _WS.sub(" ", str(value or "").strip())
    if _CONTROL.search(text):
        raise ValueError("control_characters_rejected")
    if _SECRET.search(text):
        raise ValueError("prohibited_or_secret_shaped")
    return text[:limit]


def _normalize_language(value: str) -> str:
    raw = _clean_text(value, limit=32).lower()
    if not raw:
        return "en"
    if not _LANGUAGE.fullmatch(raw):
        raise ValueError("language must be a BCP-47-like label")
    return raw.split("-", 1)[0]


def _normalize_buyer(value: str) -> str:
    buyer = _clean_text(value, limit=32).lower().replace(" ", "_")
    if buyer in {"consumer", "customer", "end_user", "b2c"}:
        return "consumer"
    if buyer in {"business", "b2b", "commercial"}:
        return "business"
    if buyer in {"reseller", "dropship", "dropshipper", "merchant"}:
        return "reseller"
    if buyer in {"", "unknown", "n/a", "na"}:
        return "unknown"
    return "unknown"


def _region_key(region: str) -> str:
    return _clean_text(region, limit=80).lower()


def _ambiguous(product_query: str, category: str) -> bool:
    tokens = [token for token in re.split(r"[^\w]+", product_query.lower()) if token]
    if len(product_query) < 3:
        return True
    if not tokens:
        return True
    if all(token in AMBIGUOUS_TOKENS for token in tokens) and not category.strip():
        return True
    if len(tokens) == 1 and tokens[0] in AMBIGUOUS_TOKENS:
        return True
    return False


def _append_unique(
    bucket: list[PlannedQuery],
    seen: set[str],
    item: PlannedQuery,
) -> None:
    key = item.query_text.casefold()
    if not item.query_text or key in seen:
        return
    if len(bucket) >= MAX_QUERIES_PER_SOURCE:
        return
    seen.add(key)
    bucket.append(item)


def _combine(*parts: str) -> str:
    return _WS.sub(" ", " ".join(part for part in parts if part).strip())


def build_research_query_plan(
    brief: ProductResearchBrief | Mapping[str, Any],
) -> ResearchQueryPlan:
    """Build a bounded, deterministic, source-specific query plan.

    Offline only: no provider calls, no URL assembly, no evidence claims.
    """
    normalized = coerce_brief(brief)
    product_query = _clean_text(normalized.product_query)
    category = _clean_text(normalized.category)
    region = _clean_text(normalized.region, limit=80)
    language = _normalize_language(normalized.language)
    buyer = _normalize_buyer(normalized.intended_buyer)
    brief_out = ProductResearchBrief(
        product_query=product_query,
        category=category,
        region=region,
        language=language,
        intended_buyer=buyer,
    )

    flags: list[str] = []
    if _ambiguous(product_query, category):
        flags.append("ambiguous_brief")
    language_supported = language in SUPPORTED_LANGUAGES
    if not language_supported:
        flags.append("unsupported_language")

    lex_lang = language if language_supported else "en"
    region_labels = REGION_LABELS.get(_region_key(region), ())
    family_mods = FAMILY_MODIFIERS.get(lex_lang, FAMILY_MODIFIERS["en"])
    buyer_mods = BUYER_MODIFIERS.get(lex_lang, BUYER_MODIFIERS["en"]).get(buyer, {})
    category_synonyms = CATEGORY_SYNONYMS.get(lex_lang, {}).get(category.lower(), ())
    localized_query = (
        QUERY_LOCALIZATIONS.get(language, {}).get(product_query.lower())
        if language_supported
        else None
    )

    planned: list[PlannedQuery] = []
    for family in SOURCE_FAMILIES:
        family_bucket: list[PlannedQuery] = []
        seen: set[str] = set()
        lang_applied = language if language_supported else "unsupported"

        _append_unique(
            family_bucket,
            seen,
            PlannedQuery(
                query_text=product_query,
                source_family=family,
                rationale=(
                    f"Preserves the operator's original query for {family}. "
                    "A generated query is not evidence or proof of demand."
                ),
                is_original=True,
                language_applied=lang_applied,
                region_applied=region,
                tags=("original", family),
            ),
        )

        if language_supported and localized_query and localized_query.casefold() != product_query.casefold():
            _append_unique(
                family_bucket,
                seen,
                PlannedQuery(
                    query_text=localized_query,
                    source_family=family,
                    rationale=(
                        f"Bounded localization of the product phrase for {family} "
                        f"in language '{language}'. Not an invented attribute."
                    ),
                    language_applied=lang_applied,
                    region_applied=region,
                    tags=("localization", family),
                ),
            )

        if language_supported:
            # Priority order keeps region + buyer + family cues inside the
            # per-source cap before optional category synonyms.
            if region_labels:
                label = region_labels[0]
                _append_unique(
                    family_bucket,
                    seen,
                    PlannedQuery(
                        query_text=_combine(product_query, label),
                        source_family=family,
                        rationale=(
                            f"Region label '{label}' attached for localized search. "
                            "Not a claim that inventory or demand exists in-region."
                        ),
                        language_applied=lang_applied,
                        region_applied=region,
                        tags=("region", family),
                    ),
                )

            for modifier in family_mods.get(family, ())[:1]:
                _append_unique(
                    family_bucket,
                    seen,
                    PlannedQuery(
                        query_text=_combine(product_query, modifier),
                        source_family=family,
                        rationale=(
                            f"Source-specific {family} intent modifier. "
                            "Marketplace hits do not prove demand or supplier availability."
                        ),
                        language_applied=lang_applied,
                        region_applied=region,
                        tags=("family_modifier", family),
                    ),
                )

            for modifier in buyer_mods.get(family, ())[:1]:
                _append_unique(
                    family_bucket,
                    seen,
                    PlannedQuery(
                        query_text=_combine(product_query, modifier),
                        source_family=family,
                        rationale=f"Buyer-intent ({buyer}) variant scoped to {family} only.",
                        language_applied=lang_applied,
                        region_applied=region,
                        tags=("buyer_intent", buyer, family),
                    ),
                )

            for synonym in category_synonyms[:1]:
                _append_unique(
                    family_bucket,
                    seen,
                    PlannedQuery(
                        query_text=_combine(product_query, synonym),
                        source_family=family,
                        rationale=(
                            f"Bounded category synonym for {family} from the offline lexicon. "
                            "Does not invent product attributes."
                        ),
                        language_applied=lang_applied,
                        region_applied=region,
                        tags=("category_synonym", family),
                    ),
                )

        planned.extend(family_bucket)

    planned = planned[:MAX_TOTAL_QUERIES]
    # Stable family-major order already from SOURCE_FAMILIES loop.
    limitations = (
        "Offline query planning only; no provider requests or URL assembly.",
        "Generated queries are not evidence, demand proof, or supplier proof.",
        "Marketplace, supplier, and consumer-attention queries stay distinct.",
        "Unsupported languages do not receive invented translations.",
        "Synonym expansion is bounded by an explicit offline lexicon.",
        "Not live validation and not launch authorization.",
    )
    ok = "ambiguous_brief" not in flags
    return ResearchQueryPlan(
        plan_version=PLAN_VERSION,
        brief=brief_out,
        queries=tuple(planned),
        flags=tuple(flags),
        limitations=limitations,
        ok=ok,
        live_validated=False,
        launch_authorized=False,
        authority="query_planning_only",
    )


__all__ = ["build_research_query_plan"]
