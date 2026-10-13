"""Brief-driven offline product-opportunity research runner.

Composes existing marketplace, supplier-feasibility, and consumer-attention
authorities from a minimal research brief, then reuses Product Opportunity
Synthesis as the sole decision layer. No second scorer, registry, or
orchestrator. Live provider calls stay disabled unless a future approved
credential path exists; this module never reads credentials or authorizes them.
"""
from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol

from backend.adapters.research.consumer_attention import normalize_record as normalize_attention
from backend.adapters.research.marketplace_trends import normalize_record as normalize_marketplace
from backend.adapters.research.supplier_feasibility import normalize_record as normalize_supplier
from evaluation.commerce.consumer_attention import build_report as build_attention_report
from evaluation.commerce.marketplace_trends import build_report as build_marketplace_report
from evaluation.commerce.opportunity_synthesis import build_product_opportunity_synthesis
from evaluation.commerce.supplier_feasibility import build_report as build_supplier_report
from evaluation.companyos.resource_execution_governor import (
    ExecutionDecisionRequest,
    evaluate_execution_request,
)
from services.research_query_plan import build_research_query_plan

REPORT_VERSION = "brief-driven-product-research-v1"

SOURCE_STATUSES = frozenset(
    {
        "collected",
        "partial",
        "not_configured",
        "disabled_by_policy",
        "timed_out",
        "unavailable",
        "quota_exhausted",
    }
)
PILLARS = ("marketplace", "supplier", "consumer_attention")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SLUG = re.compile(r"[^a-z0-9]+")


def _text(value: Any, limit: int = 160) -> str:
    text = _CONTROL.sub("", str(value or "")).strip()
    return text[:limit]


def _slug(value: str, *, fallback: str = "candidate") -> str:
    slug = _SLUG.sub("-", value.casefold()).strip("-")
    return (slug or fallback)[:80]


@dataclass(frozen=True)
class ResearchBrief:
    """Minimal operator brief — no competitor URLs, supplier CSVs, or hand rows."""

    product_query: str
    category: str
    target_region: str
    language: str
    intended_buyer: str
    max_candidates: int = 5
    evidence_mode: str = "fixture_demo"
    workspace_id: str = ""

    def __post_init__(self) -> None:
        if not _text(self.product_query, 200):
            raise ValueError("product_query is required")
        if not _text(self.category, 120):
            raise ValueError("category is required")
        if not _text(self.target_region, 80):
            raise ValueError("target_region is required")
        if not _text(self.language, 32):
            raise ValueError("language is required")
        if not _text(self.intended_buyer, 160):
            raise ValueError("intended_buyer is required")
        if not isinstance(self.max_candidates, int) or not 1 <= self.max_candidates <= 25:
            raise ValueError("max_candidates must be between 1 and 25")
        if self.evidence_mode not in {"fixture_demo", "manual_import"}:
            raise ValueError("evidence_mode must be fixture_demo or manual_import")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DerivedQueries:
    """Collection queries plus the canonical offline query plan.

    ``marketplace_query`` / ``supplier_query`` / ``attention_query`` are the
    primary strings used for fixture/fake collection. ``planned_queries`` and
    ``query_plan`` come from ``services.research_query_plan`` and are labeled
    as plans only — never collected evidence or demand proof.
    """

    candidate_id: str
    marketplace_query: str
    supplier_query: str
    attention_query: str
    notes: tuple[str, ...] = ()
    planned_queries: tuple[Mapping[str, Any], ...] = ()
    query_plan: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "marketplace_query": self.marketplace_query,
            "supplier_query": self.supplier_query,
            "attention_query": self.attention_query,
            "notes": list(self.notes),
            "planned_queries": [dict(item) for item in self.planned_queries],
            "query_plan": dict(self.query_plan),
            "planned_queries_are_evidence": False,
        }


@dataclass(frozen=True)
class SourceCollectResult:
    """Raw outcome from one pillar source client before report building."""

    status: str
    records: tuple[Any, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    freshness_label: str = "unavailable"
    assumptions: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"unsupported source status: {self.status}")


@dataclass(frozen=True)
class SourceOutcome:
    pillar: str
    status: str
    evidence_mode: str
    query: str
    record_count: int
    report: Mapping[str, Any] | None
    provenance: tuple[str, ...]
    freshness_label: str
    warnings: tuple[str, ...]
    assumptions: tuple[str, ...]
    currencies: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "pillar": self.pillar,
            "status": self.status,
            "evidence_mode": self.evidence_mode,
            "query": self.query,
            "record_count": self.record_count,
            "report_present": self.record_count > 0,
            "empty_placeholder_report": self.report is not None and self.record_count == 0,
            "provenance": list(self.provenance),
            "freshness_label": self.freshness_label,
            "warnings": list(self.warnings),
            "assumptions": list(self.assumptions),
            "currencies": list(self.currencies),
        }


class MarketplaceSourceClient(Protocol):
    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult: ...


class SupplierSourceClient(Protocol):
    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult: ...


class AttentionSourceClient(Protocol):
    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult: ...


@dataclass
class FakeMarketplaceClient:
    """Injectable fake marketplace client for fixture tests."""

    status: str = "collected"
    rows: tuple[Mapping[str, Any], ...] = ()
    sleep_s: float = 0.0

    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult:
        if self.sleep_s > timeout_s:
            return SourceCollectResult(status="timed_out", warnings=("marketplace_client_timed_out",))
        if self.status != "collected" and self.status != "partial":
            return SourceCollectResult(status=self.status, warnings=(f"marketplace_{self.status}",))
        if self.sleep_s > 0:
            time.sleep(self.sleep_s)
        records = []
        currencies: list[str] = []
        for row in self.rows:
            payload = dict(row)
            payload.setdefault("query", query)
            payload.setdefault("candidate_id", _slug(brief.product_query))
            item = normalize_marketplace(payload, default_marketplace="amazon", mode="fixture")
            if item is None:
                continue
            records.append(item)
            if item.currency:
                currencies.append(item.currency.upper())
        status = self.status if records else "unavailable"
        if self.status == "partial" and records:
            status = "partial"
        return SourceCollectResult(
            status=status,
            records=tuple(records),
            provenance=("fake_marketplace_client", "normalize_record", "fixture"),
            freshness_label="fixture_deterministic",
            assumptions=("marketplace_fixture_not_live_demand",),
            currencies=tuple(sorted(set(currencies))),
            warnings=() if records else ("marketplace_records_empty",),
        )


@dataclass
class FakeSupplierClient:
    status: str = "collected"
    rows: tuple[Mapping[str, Any], ...] = ()
    sleep_s: float = 0.0

    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult:
        if self.sleep_s > timeout_s:
            return SourceCollectResult(status="timed_out", warnings=("supplier_client_timed_out",))
        if self.status not in {"collected", "partial"}:
            return SourceCollectResult(status=self.status, warnings=(f"supplier_{self.status}",))
        if self.sleep_s > 0:
            time.sleep(self.sleep_s)
        records = []
        currencies: list[str] = []
        for row in self.rows:
            payload = dict(row)
            payload.setdefault("query", query)
            payload.setdefault("candidate_id", _slug(brief.product_query))
            payload.setdefault("destination_region", brief.target_region)
            item = normalize_supplier(payload, default_supplier="cj", default_source_type="fixture_demo", mode="fixture")
            if item is None:
                continue
            records.append(item)
            if item.currency:
                currencies.append(str(item.currency).upper())
            if item.shipping_currency:
                currencies.append(str(item.shipping_currency).upper())
        status = self.status if records else "unavailable"
        if self.status == "partial" and records:
            status = "partial"
        return SourceCollectResult(
            status=status,
            records=tuple(records),
            provenance=("fake_supplier_client", "normalize_record", "fixture"),
            freshness_label="fixture_deterministic",
            assumptions=("supplier_fixture_not_live_proof", "attention_is_not_supplier_proof"),
            currencies=tuple(sorted(set(currencies))),
            warnings=() if records else ("supplier_records_empty",),
        )


@dataclass
class FakeAttentionClient:
    status: str = "collected"
    rows: tuple[Mapping[str, Any], ...] = ()
    sleep_s: float = 0.0

    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult:
        if self.sleep_s > timeout_s:
            return SourceCollectResult(status="timed_out", warnings=("attention_client_timed_out",))
        if self.status not in {"collected", "partial"}:
            return SourceCollectResult(status=self.status, warnings=(f"attention_{self.status}",))
        if self.sleep_s > 0:
            time.sleep(self.sleep_s)
        records = []
        for row in self.rows:
            payload = dict(row)
            payload.setdefault("query", query)
            payload.setdefault("candidate_id", _slug(brief.product_query))
            payload.setdefault("geography", brief.target_region)
            payload.setdefault("language", brief.language)
            item = normalize_attention(payload, default_platform="tiktok", default_source_type="tiktok_creative_center_snapshot", mode="fixture")
            if item is None:
                continue
            records.append(item)
        status = self.status if records else "unavailable"
        if self.status == "partial" and records:
            status = "partial"
        return SourceCollectResult(
            status=status,
            records=tuple(records),
            provenance=("fake_attention_client", "normalize_record", "fixture"),
            freshness_label="fixture_deterministic",
            assumptions=("consumer_attention_is_not_supplier_proof", "attention_is_not_marketplace_listing"),
            currencies=(),
            warnings=() if records else ("attention_records_empty",),
        )


@dataclass
class StatusOnlyClient:
    """Client that always returns an explicit non-success status."""

    status: str
    pillar: str = "source"

    def collect(self, query: str, *, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult:
        return SourceCollectResult(status=self.status, warnings=(f"{self.pillar}_{self.status}",))


def _map_buyer_intent(intended_buyer: str) -> str:
    """Map free-text buyer persona onto the planner's bounded buyer intents."""
    text = _text(intended_buyer, 160).casefold()
    if any(token in text for token in ("reseller", "dropship", "revendedor")):
        return "reseller"
    if any(token in text for token in ("business", "b2b", "commercial", "oficina", "office")):
        return "business"
    if any(token in text for token in ("consumer", "customer", "home", "casa", "barista", "personal")):
        return "consumer"
    return "unknown"


def _primary_collection_query(plan_queries: list[Any], family: str, *, fallback: str) -> str:
    """Pick one collection string per family from the canonical plan.

    Prefer a family_modifier / buyer_intent row so pillars stay distinct, then
    any non-original variant, then the preserved original. Never treats the
    plan row as collected evidence.
    """
    family_rows = [item for item in plan_queries if getattr(item, "source_family", None) == family]
    for tag in ("family_modifier", "buyer_intent"):
        for item in family_rows:
            if tag in getattr(item, "tags", ()):
                return item.query_text
    for item in family_rows:
        if not item.is_original:
            return item.query_text
    for item in family_rows:
        if item.is_original:
            return item.query_text
    return fallback


def derive_queries(brief: ResearchBrief) -> DerivedQueries:
    """Compose pillar collection queries via ``services.research_query_plan``.

    This runner does not maintain a second lexicon or planner. Planned variants
    are attached as plans only (`is_evidence=false`).
    """
    product = _text(brief.product_query, 160)
    candidate_id = _slug(product)
    plan = build_research_query_plan(
        {
            "product_query": product,
            "category": _text(brief.category, 120),
            "region": _text(brief.target_region, 80),
            "language": _text(brief.language, 32),
            "intended_buyer": _map_buyer_intent(brief.intended_buyer),
        }
    )
    plan_dict = plan.to_dict()
    planned_queries = tuple(
        {
            **item.to_dict(),
            "role": "plan",
            "is_plan": True,
            "is_evidence": False,
            "is_collected_evidence": False,
        }
        for item in plan.queries
    )
    marketplace_query = _primary_collection_query(list(plan.queries), "marketplace", fallback=product)
    supplier_query = _primary_collection_query(list(plan.queries), "supplier", fallback=product)
    attention_query = _primary_collection_query(list(plan.queries), "consumer_attention", fallback=product)
    notes = (
        "queries_composed_from_services_research_query_plan",
        "planned_queries_are_not_collected_evidence",
        "planned_queries_are_not_demand_or_supplier_proof",
        "no_second_lexicon_in_brief_driven_runner",
        "no_manual_competitor_urls_required",
        "no_supplier_csv_required",
        "no_hand_entered_observations_required",
        f"query_plan_ok:{plan.ok}",
        *tuple(f"query_plan_flag:{flag}" for flag in plan.flags),
    )
    return DerivedQueries(
        candidate_id=candidate_id,
        marketplace_query=marketplace_query,
        supplier_query=supplier_query,
        attention_query=attention_query,
        notes=notes,
        planned_queries=planned_queries,
        query_plan=plan_dict,
    )


def default_fixture_marketplace_rows(brief: ResearchBrief, queries: DerivedQueries) -> tuple[dict[str, Any], ...]:
    return (
        {
            "candidate_id": queries.candidate_id,
            "query": queries.marketplace_query,
            "marketplace": "amazon",
            "source_type": "amazon_best_sellers_snapshot",
            "rank_position": 12,
            "best_seller_badge": False,
            "trend_label": "steady",
            "search_growth_signal": 0.42,
            "review_count": 180,
            "rating": 4.2,
            "price": 39.99,
            "currency": "USD",
            "seller_count": 14,
            "availability": "in_stock",
            "shipping_signal": "standard",
            "category_id": _text(brief.category, 80),
            "source_confidence": 0.55,
            "field_provenance": {"price": "fixture", "review_count": "fixture"},
        },
    )


def default_fixture_supplier_rows(brief: ResearchBrief, queries: DerivedQueries) -> tuple[dict[str, Any], ...]:
    return (
        {
            "candidate_id": queries.candidate_id,
            "query": queries.supplier_query,
            "supplier": "cj",
            "source_type": "fixture_demo",
            "supplier_product_id": f"FIX-{queries.candidate_id[:24]}",
            "supplier_title": _text(brief.product_query, 120),
            "unit_cost": 11.5,
            "currency": "USD",
            "shipping_cost": 4.0,
            "shipping_currency": "USD",
            "moq": 1,
            "inventory_status": "in_stock",
            "inventory_quantity": 200,
            "warehouse_region": "CN",
            "destination_region": brief.target_region,
            "fulfillment_method": "supplier_direct",
            "delivery_window": "8-15 days",
            "source_confidence": 0.5,
            "field_provenance": {
                "unit_cost": "fixture",
                "shipping_cost": "fixture",
                "inventory_quantity": "fixture",
            },
        },
    )


def default_fixture_attention_rows(brief: ResearchBrief, queries: DerivedQueries) -> tuple[dict[str, Any], ...]:
    return (
        {
            "candidate_id": queries.candidate_id,
            "query": queries.attention_query,
            "source": "fixture_attention",
            "source_type": "tiktok_creative_center_snapshot",
            "platform": "tiktok",
            "content_title": f"{brief.product_query} demo",
            "hook": f"Why {brief.intended_buyer} look at {brief.product_query}",
            "angle": "convenience",
            "pain_point": f"{brief.intended_buyer} need a simpler {brief.category}",
            "desired_outcome": f"easier {brief.product_query}",
            "format": "ugc_demo",
            "creative_format": "hands_only_demo",
            "creator_style": "creator_demo",
            "view_count": 12000,
            "like_count": 800,
            "comment_count": 40,
            "geography": brief.target_region,
            "language": brief.language,
            "source_confidence": 0.5,
        },
    )


def build_default_fixture_clients(brief: ResearchBrief, queries: DerivedQueries) -> tuple[FakeMarketplaceClient, FakeSupplierClient, FakeAttentionClient]:
    return (
        FakeMarketplaceClient(rows=default_fixture_marketplace_rows(brief, queries)),
        FakeSupplierClient(rows=default_fixture_supplier_rows(brief, queries)),
        FakeAttentionClient(rows=default_fixture_attention_rows(brief, queries)),
    )


@dataclass(frozen=True)
class AuthorityGateResult:
    screening_allowed: bool
    provider_pull_authorized: bool
    screening_outcome: str
    provider_pull_outcome: str
    notes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_authority_gates(*, workspace_id: str = "offline-brief-research") -> AuthorityGateResult:
    """Resource Execution Governor simulation — never authorizes live pulls."""
    screen = evaluate_execution_request(
        ExecutionDecisionRequest(
            "brief-screen",
            "screen_product_opportunities",
            "intelligence",
            "intelligence",
            workspace_id or "offline-brief-research",
            0,
            "report_generation_quota",
        )
    )
    provider = evaluate_execution_request(
        ExecutionDecisionRequest(
            "brief-provider-pull",
            "run_provider_data_pull",
            "provider",
            "intelligence",
            workspace_id or "offline-brief-research",
            1,
            "data_provider_budget",
            provider_id="dataforseo",
            terms_privacy_complete=False,
            approval_state="not_requested",
        )
    )
    notes = (
        "approval_ledger_simulation_is_not_live_authority",
        "offline_or_simulated_approval_does_not_authorize_live_calls",
        f"screening_outcome:{screen.outcome}",
        f"provider_pull_outcome:{provider.outcome}",
    )
    return AuthorityGateResult(
        screening_allowed=screen.outcome == "allow",
        provider_pull_authorized=False,
        screening_outcome=screen.outcome,
        provider_pull_outcome=provider.outcome,
        notes=notes,
    )


def _currency_notes(outcomes: Mapping[str, SourceOutcome]) -> tuple[str, ...]:
    currencies: set[str] = set()
    for outcome in outcomes.values():
        currencies.update(outcome.currencies)
    notes = ["currencies_are_not_converted", "no_exchange_rate_invented"]
    if len(currencies) > 1:
        notes.append("mixed_currencies_observed_keep_separate:" + ",".join(sorted(currencies)))
    elif currencies:
        notes.append("single_currency_observed:" + next(iter(currencies)))
    else:
        notes.append("no_currency_observed")
    return tuple(notes)


def _empty_pillar_report(pillar: str, *, evidence_mode: str, status: str) -> dict[str, Any]:
    """Explicit empty pillar so synthesis keeps three-way weights and never invents evidence."""
    base = {
        "evidence_mode": evidence_mode,
        "candidates": [],
        "warnings": [f"{pillar}_{status}", "missing_evidence_not_treated_as_zero_or_positive"],
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "candidate_count": 0,
    }
    if pillar == "marketplace":
        base.update({"source_count": 0, "marketplaces_observed": [], "top_candidate_id": None, "next_best_action": "supply_marketplace_evidence"})
    elif pillar == "supplier":
        base.update({"top_candidate_id": None, "next_best_action": "supply_supplier_evidence"})
    else:
        base.update({"evidence_count": 0, "platforms_observed": [], "top_candidate_id": None, "next_best_action": "expand_consumer_research"})
    return base


def _compatible_reference_prices(
    marketplace_report: Mapping[str, Any] | None,
    *,
    supplier_currencies: tuple[str, ...],
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Pass sell prices only when marketplace and supplier currencies are a single shared code."""
    if not marketplace_report or not supplier_currencies:
        return None, ("target_sell_prices_omitted_without_shared_currency",)
    market_currencies: set[str] = set()
    prices: dict[str, Any] = {}
    for item in marketplace_report.get("candidates", []):
        if not isinstance(item, Mapping):
            continue
        evidence = item.get("evidence") or []
        if not evidence or not isinstance(evidence[0], Mapping):
            continue
        currency = str(evidence[0].get("currency") or "").upper()
        if currency:
            market_currencies.add(currency)
        if item.get("candidate_id") and evidence[0].get("price") is not None:
            prices[str(item["candidate_id"])] = evidence[0].get("price")
    supplier_set = {str(item).upper() for item in supplier_currencies if item}
    if not prices:
        return None, ("target_sell_prices_unavailable",)
    if len(market_currencies) != 1 or market_currencies != supplier_set:
        return None, (
            "target_sell_prices_omitted_due_to_currency_mismatch",
            "currencies_are_not_converted",
            "no_exchange_rate_invented",
        )
    return prices, ("target_sell_prices_same_currency_only:" + next(iter(market_currencies)),)


def _bound_records_by_candidate(records: tuple[Any, ...], max_candidates: int) -> tuple[Any, ...]:
    """Keep records for the first ``max_candidates`` distinct candidate_ids (stable order)."""
    selected_ids: list[str] = []
    for item in records:
        candidate_id = str(getattr(item, "candidate_id", "") or "")
        if not candidate_id:
            continue
        if candidate_id not in selected_ids:
            if len(selected_ids) >= max_candidates:
                continue
            selected_ids.append(candidate_id)
    allowed = set(selected_ids)
    return tuple(item for item in records if str(getattr(item, "candidate_id", "") or "") in allowed)


def _build_pillar_outcome(
    pillar: str,
    query: str,
    collected: SourceCollectResult,
    *,
    evidence_mode: str,
    max_candidates: int,
    marketplace_report_for_prices: Mapping[str, Any] | None = None,
) -> SourceOutcome:
    if collected.status not in {"collected", "partial"} or not collected.records:
        status = collected.status if collected.status in SOURCE_STATUSES else "unavailable"
        return SourceOutcome(
            pillar=pillar,
            status=status,
            evidence_mode=evidence_mode,
            query=query,
            record_count=0,
            # Empty report (not None): keeps synthesis three-pillar weights; still zero evidence.
            report=_empty_pillar_report(pillar, evidence_mode=evidence_mode, status=status),
            provenance=collected.provenance + ("empty_pillar_report",),
            freshness_label=collected.freshness_label,
            warnings=collected.warnings + ("missing_evidence_not_treated_as_zero_or_positive",),
            assumptions=collected.assumptions + ("missing_pillar_scored_as_absent_not_favorable",),
            currencies=collected.currencies,
        )

    bounded = _bound_records_by_candidate(collected.records, max_candidates)
    bound_assumptions: tuple[str, ...] = ()
    bound_warnings: tuple[str, ...] = ()
    if len(bounded) < len(collected.records):
        bound_assumptions = (f"max_candidates_applied:{max_candidates}",)
        bound_warnings = ("records_truncated_to_max_candidates",)
    currencies = tuple(
        dict.fromkeys(
            str(getattr(item, "currency", "") or "").upper()
            for item in bounded
            if getattr(item, "currency", None)
        )
    ) or collected.currencies

    extra_assumptions: tuple[str, ...] = ()
    if pillar == "marketplace":
        report = build_marketplace_report(list(bounded), evidence_mode=evidence_mode).to_dict()
    elif pillar == "supplier":
        reference_prices, price_notes = _compatible_reference_prices(
            marketplace_report_for_prices,
            supplier_currencies=currencies,
        )
        extra_assumptions = price_notes
        report = build_supplier_report(
            list(bounded),
            evidence_mode=evidence_mode,
            target_sell_prices=reference_prices,
        ).to_dict()
    else:
        report = build_attention_report(list(bounded), evidence_mode=evidence_mode).to_dict()

    return SourceOutcome(
        pillar=pillar,
        status=collected.status,
        evidence_mode=str(report.get("evidence_mode") or evidence_mode),
        query=query,
        record_count=len(bounded),
        report=report,
        provenance=collected.provenance + (f"{pillar}_build_report", "max_candidates_bound"),
        freshness_label=collected.freshness_label,
        warnings=collected.warnings
        + bound_warnings
        + tuple(str(item) for item in report.get("warnings", []) if isinstance(item, str)),
        assumptions=collected.assumptions + bound_assumptions + extra_assumptions,
        currencies=currencies,
    )


def _call_with_timeout(client: Any, query: str, brief: ResearchBrief, timeout_s: float) -> SourceCollectResult:
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.collect, query, brief=brief, timeout_s=timeout_s)
        try:
            return future.result(timeout=timeout_s + 0.05)
        except FuturesTimeoutError:
            return SourceCollectResult(status="timed_out", warnings=("client_wall_timeout",))
        except Exception as exc:  # noqa: BLE001 — fail closed per source
            return SourceCollectResult(status="unavailable", warnings=(f"client_error:{type(exc).__name__}",))


_RESEARCH_STEP_PRIORITY = (
    "not_configured",
    "disabled_by_policy",
    "quota_exhausted",
    "timed_out",
    "unavailable",
    "partial",
)
_PILLAR_RESEARCH_ORDER = ("marketplace", "supplier", "consumer_attention")


def choose_next_research_step(
    outcomes: Mapping[str, SourceOutcome],
    *,
    synthesis_next_best_action: str = "",
) -> str:
    """Pick exactly one offline research step from explicit source statuses.

    Missing or partial pillars outrank synthesis commercial advice. Planned
    queries alone never satisfy a pillar.
    """
    by_status: dict[str, list[str]] = {status: [] for status in _RESEARCH_STEP_PRIORITY}
    for pillar in _PILLAR_RESEARCH_ORDER:
        outcome = outcomes.get(pillar)
        if outcome is None:
            by_status["unavailable"].append(pillar)
            continue
        if outcome.status == "collected" and outcome.record_count > 0:
            continue
        status = outcome.status if outcome.status in by_status else "unavailable"
        by_status[status].append(pillar)
    for status in _RESEARCH_STEP_PRIORITY:
        pillars = by_status.get(status) or []
        if pillars:
            return f"supply_{pillars[0]}_offline_evidence:{status}"
    action = _text(synthesis_next_best_action, 240)
    return action or "review_synthesis_recommendation_offline"


@dataclass
class BriefDrivenResearchReport:
    report_version: str
    brief: ResearchBrief
    derived_queries: DerivedQueries
    source_outcomes: dict[str, SourceOutcome]
    synthesis: Mapping[str, Any] | None
    authority: AuthorityGateResult
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]
    currency_notes: tuple[str, ...]
    execution_authorized: bool = False
    network_calls: bool = False
    read_only: bool = True
    mutated: bool = False
    live_provider_calls: bool = False
    next_best_action: str = ""
    next_research_step: str = ""
    fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "brief": self.brief.to_dict(),
            "derived_queries": self.derived_queries.to_dict(),
            "source_outcomes": {key: value.to_dict() for key, value in self.source_outcomes.items()},
            "pillar_reports": {
                key: (value.report if value.report is not None else None)
                for key, value in self.source_outcomes.items()
            },
            "synthesis": dict(self.synthesis) if isinstance(self.synthesis, Mapping) else None,
            "authority": self.authority.to_dict(),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "currency_notes": list(self.currency_notes),
            "execution_authorized": False,
            "launch_authorized": False,
            "network_calls": False,
            "read_only": True,
            "mutated": False,
            "live_provider_calls": False,
            "live_validated": False,
            "evidence_mode": self.brief.evidence_mode,
            "next_best_action": self.next_best_action,
            "next_research_step": self.next_research_step,
            "fingerprint": self.fingerprint,
            "requires_future_approval_or_credentials": [
                "Approval Ledger human-approved provider policy before any live adapter",
                "Credential references (never secret values) for marketplace/supplier/attention providers",
                "Terms/privacy and output-contract review for each provider",
                "Budget and Resource Execution Governor quotas for provider pulls",
            ],
        }


def run_brief_driven_research(
    brief: ResearchBrief,
    *,
    marketplace_client: MarketplaceSourceClient | None = None,
    supplier_client: SupplierSourceClient | None = None,
    attention_client: AttentionSourceClient | None = None,
    allow_live: bool = False,
    max_concurrency: int = 1,
    timeout_s: float = 2.0,
    use_default_fixture_clients: bool = False,
) -> BriefDrivenResearchReport:
    """Run a bounded, offline brief → sources → synthesis pass.

    ``allow_live`` is accepted only to fail closed: live calls are never enabled here.
    """
    if allow_live:
        raise ValueError("live_provider_calls_disabled_pending_approval_ledger")
    if not isinstance(timeout_s, (int, float)) or timeout_s <= 0 or timeout_s > 30:
        raise ValueError("timeout_s must be in (0, 30]")
    if not isinstance(max_concurrency, int) or not 1 <= max_concurrency <= 3:
        raise ValueError("max_concurrency must be between 1 and 3")

    queries = derive_queries(brief)
    authority = evaluate_authority_gates(workspace_id=brief.workspace_id or "offline-brief-research")
    if not authority.screening_allowed:
        raise ValueError("screening_blocked_by_resource_execution_governor")

    if marketplace_client is None and supplier_client is None and attention_client is None:
        if use_default_fixture_clients:
            marketplace_client, supplier_client, attention_client = build_default_fixture_clients(brief, queries)
        else:
            marketplace_client = StatusOnlyClient("not_configured", "marketplace")
            supplier_client = StatusOnlyClient("not_configured", "supplier")
            attention_client = StatusOnlyClient("not_configured", "attention")

    marketplace_client = marketplace_client or StatusOnlyClient("not_configured", "marketplace")
    supplier_client = supplier_client or StatusOnlyClient("not_configured", "supplier")
    attention_client = attention_client or StatusOnlyClient("not_configured", "attention")

    jobs: list[tuple[str, str, Any]] = [
        ("marketplace", queries.marketplace_query, marketplace_client),
        ("supplier", queries.supplier_query, supplier_client),
        ("consumer_attention", queries.attention_query, attention_client),
    ]

    collected: dict[str, SourceCollectResult] = {}
    if max_concurrency == 1:
        for pillar, query, client in jobs:
            collected[pillar] = _call_with_timeout(client, query, brief, float(timeout_s))
    else:
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pillar: pool.submit(_call_with_timeout, client, query, brief, float(timeout_s))
                for pillar, query, client in jobs
            }
            for pillar, future in futures.items():
                try:
                    collected[pillar] = future.result(timeout=float(timeout_s) + 0.25)
                except FuturesTimeoutError:
                    collected[pillar] = SourceCollectResult(status="timed_out", warnings=("pool_timeout",))

    outcomes: dict[str, SourceOutcome] = {}
    market_outcome = _build_pillar_outcome(
        "marketplace",
        queries.marketplace_query,
        collected["marketplace"],
        evidence_mode=brief.evidence_mode,
        max_candidates=brief.max_candidates,
    )
    outcomes["marketplace"] = market_outcome
    outcomes["supplier"] = _build_pillar_outcome(
        "supplier",
        queries.supplier_query,
        collected["supplier"],
        evidence_mode=brief.evidence_mode,
        max_candidates=brief.max_candidates,
        marketplace_report_for_prices=market_outcome.report,
    )
    outcomes["consumer_attention"] = _build_pillar_outcome(
        "consumer_attention",
        queries.attention_query,
        collected["consumer_attention"],
        evidence_mode=brief.evidence_mode,
        max_candidates=brief.max_candidates,
    )

    synthesis = build_product_opportunity_synthesis(
        outcomes["marketplace"].report,
        outcomes["supplier"].report,
        outcomes["consumer_attention"].report,
        client_context={
            "product_query": brief.product_query,
            "category": brief.category,
            "target_region": brief.target_region,
            "language": brief.language,
            "intended_buyer": brief.intended_buyer,
            "evidence_mode": brief.evidence_mode,
        },
    ).to_dict()

    currency_notes = _currency_notes(outcomes)
    assumptions = (
        "price_cpa_ctr_budget_fx_are_planning_assumptions_when_present",
        "fixture_or_manual_evidence_is_not_live_validation",
        "marketplace_listing_is_not_verified_demand",
        "consumer_attention_is_not_supplier_proof",
        *currency_notes,
        *queries.notes,
        *authority.notes,
    )
    for outcome in outcomes.values():
        assumptions = assumptions + outcome.assumptions

    limitations = (
        "no_live_provider_calls_in_this_lane",
        "no_credentials_read",
        "no_raw_provider_payload_persistence",
        "successful_sources_preserved_when_siblings_fail",
        "missing_evidence_never_translated_to_favorable_result",
    )
    for pillar, outcome in outcomes.items():
        if outcome.status != "collected":
            limitations = limitations + (f"{pillar}_status:{outcome.status}",)

    next_action = str(synthesis.get("next_best_action") or "review_source_statuses_and_supply_offline_evidence")
    next_research_step = choose_next_research_step(outcomes, synthesis_next_best_action=next_action)
    fingerprint = hashlib.sha256(
        repr(
            (
                brief.to_dict(),
                {key: value.to_dict() for key, value in outcomes.items()},
                synthesis.get("overall_recommendation"),
                synthesis.get("top_candidate_id"),
                next_research_step,
            )
        ).encode("utf-8")
    ).hexdigest()[:24]

    return BriefDrivenResearchReport(
        report_version=REPORT_VERSION,
        brief=brief,
        derived_queries=queries,
        source_outcomes=outcomes,
        synthesis=synthesis,
        authority=authority,
        assumptions=tuple(dict.fromkeys(assumptions)),
        limitations=tuple(dict.fromkeys(limitations)),
        currency_notes=currency_notes,
        next_best_action=next_action,
        next_research_step=next_research_step,
        fingerprint=fingerprint,
    )


def render_markdown(report: BriefDrivenResearchReport | Mapping[str, Any]) -> str:
    data = report.to_dict() if isinstance(report, BriefDrivenResearchReport) else dict(report)
    brief = data.get("brief", {})
    lines = [
        "# Brief-Driven Product Opportunity Research",
        "",
        f"Report version: `{data.get('report_version')}`",
        f"Product query: **{_text(brief.get('product_query'), 160)}**",
        f"Category: {_text(brief.get('category'), 120)}",
        f"Region / language: {_text(brief.get('target_region'), 80)} / {_text(brief.get('language'), 32)}",
        f"Intended buyer: {_text(brief.get('intended_buyer'), 160)}",
        f"Execution authorized: `{bool(data.get('execution_authorized'))}`",
        f"Live provider calls: `{bool(data.get('live_provider_calls'))}`",
        "",
        "## Source statuses",
        "",
        "| Pillar | Status | Records | Freshness | Currencies |",
        "| --- | --- | ---: | --- | --- |",
    ]
    for pillar, outcome in (data.get("source_outcomes") or {}).items():
        lines.append(
            f"| {pillar} | `{outcome.get('status')}` | {outcome.get('record_count', 0)} | "
            f"{outcome.get('freshness_label')} | {', '.join(outcome.get('currencies') or []) or 'none'} |"
        )
    synthesis = data.get("synthesis") or {}
    lines += [
        "",
        "## Synthesis (canonical Product Opportunity Synthesis)",
        "",
        f"Top candidate: `{synthesis.get('top_candidate_id') or 'none'}`",
        f"Recommendation: `{synthesis.get('overall_recommendation') or 'unavailable'}`",
        f"Confidence grade: `{synthesis.get('confidence_grade') or 'unavailable'}`",
        f"Next research step: {_text(data.get('next_research_step'), 240)}",
        f"Next best action: {_text(data.get('next_best_action'), 240)}",
        "",
        "## Assumptions",
        "",
    ]
    lines.extend(f"- {item}" for item in data.get("assumptions", []))
    lines += ["", "## Limitations", ""]
    lines.extend(f"- {item}" for item in data.get("limitations", []))
    lines += ["", "## Future approval / credentials", ""]
    lines.extend(f"- {item}" for item in data.get("requires_future_approval_or_credentials", []))
    lines += [
        "",
        "This run is offline planning guidance. It does not authorize spend, publish, orders, payments, messaging, or provider mutations.",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "REPORT_VERSION",
    "SOURCE_STATUSES",
    "ResearchBrief",
    "DerivedQueries",
    "SourceCollectResult",
    "SourceOutcome",
    "FakeMarketplaceClient",
    "FakeSupplierClient",
    "FakeAttentionClient",
    "StatusOnlyClient",
    "AuthorityGateResult",
    "BriefDrivenResearchReport",
    "derive_queries",
    "choose_next_research_step",
    "evaluate_authority_gates",
    "build_default_fixture_clients",
    "run_brief_driven_research",
    "render_markdown",
]
