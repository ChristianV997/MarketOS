"""Bounded category research orchestration.

This module composes existing discovery, supplier, margin, and validation
services. It does not create stores, brands, pages, accounts, campaigns, or
orders. Every output is a dossier with source lineage and a durable cache.
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from backend.research.cache import ResearchCache
from backend.research.mode import is_research_only
from backend.validation.suppliers import quote_all
from backend.core.persistence import save_json_atomic, save_text_atomic, state_path

from .dossier_store import DossierStore
from .dossiers import CategoryDossier, EvidenceRecord, ProductDossier, SupplierEvidence, content_hash
from .portfolio import optimize_top_three, simulate_product, tipping_point

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchRunConfig:
    category: str
    max_products: int = 20
    cache_ttl_s: float = 21_600.0
    max_supplier_quotes: int = 5
    force_refresh: bool = False

    def bounded(self) -> "ResearchRunConfig":
        return ResearchRunConfig(
            category=self.category.strip() or "general",
            max_products=max(1, min(int(self.max_products), 100)),
            cache_ttl_s=max(60.0, float(self.cache_ttl_s)),
            max_supplier_quotes=max(1, min(int(self.max_supplier_quotes), 5)),
            force_refresh=self.force_refresh,
        )


def _evidence(source: str, value: dict[str, Any], *, url: str = "", quality: str = "observed") -> EvidenceRecord:
    return EvidenceRecord(
        source=source,
        source_url=url,
        value=value,
        confidence=float(value.get("confidence", value.get("score", 0.0)) or 0.0),
        quality=quality,
        cache_key=f"{source}:{content_hash(value)}",
        content_hash=content_hash(value),
    )


def run_category_research(config: ResearchRunConfig, *, cache: ResearchCache | None = None,
                          store: DossierStore | None = None) -> CategoryDossier:
    """Run one bounded, repeatable category research pass.

    Source errors degrade to evidence records and health telemetry; they never
    become positive evidence. In a normal supervised process research-only is
    required, which prevents accidentally using this function as a launch path.
    """
    cfg = config.bounded()
    cache = cache or ResearchCache()
    store = store or DossierStore()
    started = time.perf_counter()
    query_key = f"discover:{cfg.category.lower()}:{cfg.max_products}"

    discovered = None if cfg.force_refresh else cache.get(query_key, ttl_s=cfg.cache_ttl_s)
    if discovered is None:
        source_started = time.perf_counter()
        try:
            from backend.discovery import discover_products
            discovered = discover_products(limit=cfg.max_products)
            cache.record_source("discovery", ok=True, count=len(discovered), duration_s=time.perf_counter() - source_started)
            cache.put(query_key, discovered)
        except Exception as exc:  # noqa: BLE001
            _log.warning("category_research_discovery_failed category=%s error=%s", cfg.category, exc)
            discovered = []
            cache.record_source("discovery", ok=False, count=0, duration_s=time.perf_counter() - source_started, error=type(exc).__name__)
    else:
        cache.record_source("discovery_cache", ok=True, count=len(discovered), duration_s=0.0)

    products: list[ProductDossier] = []
    seen: set[str] = set()
    for opportunity in discovered[: cfg.max_products]:
        name = str(opportunity.get("product", "")).strip()
        if not name:
            continue
        key = hashlib.sha256(f"{cfg.category.lower()}:{name.lower()}".encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        cache_key = f"validate:{cfg.category.lower()}:{name.lower()}"
        verdict = None if cfg.force_refresh else cache.get(cache_key, ttl_s=cfg.cache_ttl_s)
        was_cached = verdict is not None
        source_started = time.perf_counter()
        try:
            if verdict is None:
                from backend.validation.validator import validate_product
                verdict = validate_product(name, category=cfg.category)
                cache.put(cache_key, verdict)
            cache.record_source("validation_cache" if was_cached else "validation", ok=True, count=1, duration_s=time.perf_counter() - source_started)
        except Exception as exc:  # noqa: BLE001
            _log.warning("category_research_validation_failed product=%s error=%s", name, exc)
            verdict = {"product": name, "recommendation": "unverified", "confidence": 0.0, "risk_flags": ["validation_error"]}
            cache.record_source("validation", ok=False, count=0, duration_s=time.perf_counter() - source_started, error=type(exc).__name__)

        supplier_offers: list[SupplierEvidence] = []
        quote_started = time.perf_counter()
        try:
            quotes = quote_all(name)[: cfg.max_supplier_quotes]
            for quote in quotes:
                supplier_offers.append(SupplierEvidence(
                    supplier_id=quote.product_id,
                    supplier_name=quote.supplier,
                    product_id=name,
                    unit_cost=quote.cost,
                    shipping_cost=quote.shipping,
                    shipping_days_min=quote.fulfillment_days,
                    shipping_days_max=quote.fulfillment_days,
                    inventory_checked_at=time.time(),
                    landed_cost=quote.landed_cost,
                    validation_status="quoted_dry_run" if is_research_only() else "quoted",
                    evidence=(_evidence("supplier_quote", quote.to_dict(), quality="quoted"),),
                ))
            cache.record_source("suppliers", ok=bool(quotes), count=len(quotes), duration_s=time.perf_counter() - quote_started,
                                error="no_quotes" if not quotes else "")
        except Exception as exc:  # noqa: BLE001
            cache.record_source("suppliers", ok=False, count=0, duration_s=time.perf_counter() - quote_started, error=type(exc).__name__)

        demand = _evidence(str(opportunity.get("source", "discovery")), {
            "signal_score": opportunity.get("signal_score", 0.0),
            "opportunity_score": opportunity.get("opportunity_score", 0.0),
            "market_saturation": opportunity.get("market_saturation"),
            "competitor_count": opportunity.get("competitor_count"),
        }, quality="signal")
        economics = dict(verdict.get("margin") or {})
        audience = {
            "segments": ["problem-aware shoppers", "value-conscious enthusiasts"],
            "basis": "research hypothesis; requires audience evidence",
        }
        experiment_matrix = tuple({
            "channel": channel,
            "angle": angle,
            "audience": segment,
            "status": "draft_research_cell",
        } for channel in ("meta", "tiktok", "google")
          for angle in ("problem_solution", "social_proof", "demonstration")
          for segment in audience["segments"])
        products.append(ProductDossier(
            name=name,
            category=cfg.category,
            demand_evidence=(demand,),
            supplier_offers=tuple(supplier_offers),
            competitor_evidence=(_evidence("competitor_summary", {
                "count": opportunity.get("competitor_count"),
                "saturation": opportunity.get("market_saturation"),
                "difficulty": opportunity.get("competition_difficulty"),
            }, quality="signal"),),
            economics=economics,
            audience_hypotheses=(audience,),
            experiment_matrix=experiment_matrix,
            recommendation=str(verdict.get("recommendation", "unverified")),
            score=float(verdict.get("confidence", 0.0) or 0.0),
        ))

    products.sort(key=lambda item: item.score, reverse=True)
    health = cache.health()
    selected = optimize_top_three(products)
    simulations = [simulate_product(item) for item in products[:3]]
    dossier = CategoryDossier(
        category=cfg.category,
        products=tuple(products),
        market_evidence=tuple(item for product in products for item in product.demand_evidence),
        audience_summary={"status": "hypotheses_pending", "source": "research_only"},
        source_health=health,
        portfolio={**selected, "simulations": simulations},
        scenarios={"products": simulations, "status": "research_only"},
        status="research_only" if is_research_only() else "dry_run_research",
        tipping_point=tipping_point(products[:3], simulations),
    )
    if os.getenv("MARKETOS_RESEARCH_OLLAMA", "false").lower() == "true":
        try:
            from .ollama import summarize_dossier
            annotation = summarize_dossier(dossier.to_dict()) or {}
            dossier = CategoryDossier(
                category=dossier.category, products=dossier.products, market_evidence=dossier.market_evidence,
                audience_summary=dossier.audience_summary, source_health=dossier.source_health,
                portfolio=dossier.portfolio, scenarios=dossier.scenarios, tipping_point=dossier.tipping_point,
                ollama_annotation=annotation, status=dossier.status, generated_at=dossier.generated_at,
            )
        except Exception as exc:  # noqa: BLE001
            _log.debug("ollama_research_annotation_failed error=%s", exc)
    store.save_dossier(dossier)
    # JSON is the machine-readable source of truth; Markdown is the human
    # review artifact. Both are local, atomic, and research-only.
    try:
        from .report import render_category_dossier_markdown
        report_stem = f"research_reports/{dossier.category_id}"
        save_json_atomic(state_path(f"{report_stem}.json"), dossier.to_dict())
        save_text_atomic(state_path(f"{report_stem}.md"), render_category_dossier_markdown(dossier))
    except Exception as exc:  # noqa: BLE001
        _log.debug("category_research_report_failed error=%s", exc)
    _log.info("category_research_done category=%s products=%d duration_s=%.2f", cfg.category, len(products), time.perf_counter() - started)
    return dossier
