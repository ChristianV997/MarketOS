"""Static audit of the MarketOS commerce/research call graph.

This module does not execute authorities. It records where measurement
should attach so the harness never invents a second scorer, economics
engine, event system, quality gate, or replay authority.
"""
from __future__ import annotations

from typing import Any


SCHEMA = "commerce-call-graph-audit-v1"

# Each row is a measured-or-classified path. `owned_by` is documentation
# only; this lane must not edit those files.
CANONICAL_PATHS: tuple[dict[str, Any], ...] = (
    {
        "path_id": "supplier_normalization",
        "authority": "evaluation.commerce.supplier_feasibility",
        "symbols": ("SupplierFeasibilityEvidence", "collapse_duplicates", "build_report"),
        "call_shape": "build_report(list[SupplierFeasibilityEvidence], evidence_mode=..., target_sell_prices=...)",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("offline evidence only", "does_not_authorize_orders"),
    },
    {
        "path_id": "supplier_unit_economics_helper",
        "authority": "evaluation.commerce.supplier_feasibility",
        "symbols": ("calculate_unit_economics",),
        "call_shape": "calculate_unit_economics(target_sell_price=..., unit_cost=..., shipping_cost=...)",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("scenario helper inside supplier feasibility", "not_backend.economics.kernel"),
    },
    {
        "path_id": "marketplace_trends",
        "authority": "evaluation.commerce.marketplace_trends",
        "symbols": ("build_report", "build_marketplace_trend_report"),
        "call_shape": "build_report(...) if present",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("demand pillar only",),
    },
    {
        "path_id": "consumer_attention",
        "authority": "evaluation.commerce.consumer_attention",
        "symbols": ("build_attention_report", "build_report"),
        "call_shape": "build_attention_report(...) if present",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("creative pillar only",),
    },
    {
        "path_id": "opportunity_synthesis",
        "authority": "evaluation.commerce.opportunity_synthesis",
        "symbols": ("build_product_opportunity_synthesis",),
        "call_shape": "build_product_opportunity_synthesis(market, supplier, consumer)",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("fusion layer", "does_not_grant_launch_authority"),
    },
    {
        "path_id": "client_safe_export",
        "authority": "evaluation.commerce.product_validation_report",
        "symbols": ("generate",),
        "call_shape": "generate(client_name=..., benchmark=nonempty, readiness=nonempty, deployment=nonempty, marketplace_trends=..., supplier_feasibility=..., consumer_attention=..., opportunity_synthesis=...)",
        "owned_by": "main",
        "live_ok": False,
        "notes": (
            "empty mapping is falsy and trips filesystem defaults",
            "adapter must pass explicit non-empty packets",
        ),
    },
    {
        "path_id": "commerce_cycle",
        "authority": "backend.commerce.loop",
        "symbols": ("run_commerce_cycle",),
        "call_shape": "run_commerce_cycle(signals=..., products=..., offers=..., top_k=1, budget=..., dry_run=True)",
        "owned_by": "main / #225",
        "live_ok": False,
        "notes": ("dry_run only", "imported via backend.commerce"),
    },
    {
        "path_id": "existing_cycle_benchmark",
        "authority": "scripts.benchmark_commerce_cycle",
        "symbols": ("benchmark",),
        "call_shape": "benchmark(runs=..., p95_limit_ms=...)",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("existing harness wrapped, not replaced", "forces INFERENCE_PROVIDERS=mock"),
    },
    {
        "path_id": "competition_normalization",
        "authority": "backend.mvp_commerce.competition_intelligence",
        "symbols": ("build_market_opportunity_report",),
        "call_shape": "build_market_opportunity_report(candidate_id, product_name, generated_at=0.0)",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("combine/score only", "gather_market_intelligence is never called"),
    },
    {
        "path_id": "competition_fetch",
        "authority": "backend.mvp_commerce.competition_intelligence",
        "symbols": ("gather_market_intelligence",),
        "call_shape": "NOT CALLED",
        "owned_by": "main",
        "live_ok": False,
        "notes": ("network-capable; excluded from this lane",),
    },
    {
        "path_id": "research_to_decision",
        "authority": "evaluation.research.research_to_decision | scripts.research_to_decision",
        "symbols": ("build_research_to_decision", "main"),
        "call_shape": "classified unavailable unless already on the checkout",
        "owned_by": "#247",
        "live_ok": False,
        "notes": ("this lane does not reimplement the path",),
    },
    {
        "path_id": "financial_kernel",
        "authority": "backend.economics.kernel",
        "symbols": ("calculate_service_economics",),
        "call_shape": "never driven by this lane",
        "owned_by": "#248 / #250",
        "live_ok": False,
        "notes": ("classify unavailable or not_run", "do not compute money here"),
    },
    {
        "path_id": "replay_identity",
        "authority": "evaluation.perf.canonical_adapters._fingerprint",
        "symbols": ("_fingerprint",),
        "call_shape": "sha256(json.dumps(canonical_payload, sort_keys=True))",
        "owned_by": "#255 measurement seam",
        "live_ok": False,
        "notes": (
            "OpenLineage-style run identity, not a second replay authority",
            "does not replace TrustOS / commercial-replay lanes",
        ),
    },
    {
        "path_id": "sandbox_preprocess",
        "authority": "evaluation.perf.commerce_engine",
        "symbols": ("process_offers", "detect_conflicts_pairwise", "detect_conflicts_indexed"),
        "call_shape": "labeled sandbox_pattern_not_production",
        "owned_by": "#255",
        "live_ok": False,
        "notes": (
            "not a MarketOS production path",
            "kept only as a readable reference + indexed comparison",
        ),
    },
)


FORBIDDEN_SECOND_AUTHORITIES = (
    "second_commerce_engine",
    "second_ranking_algorithm",
    "second_economics_engine",
    "second_quality_gate",
    "second_event_system",
    "second_replay_authority",
)


def audit() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "merge_authority": False,
        "quality_gate": False,
        "forbidden_second_authorities": list(FORBIDDEN_SECOND_AUTHORITIES),
        "paths": [dict(item) for item in CANONICAL_PATHS],
        "never_called": ("gather_market_intelligence", "run_provider_cycle", "backend.economics.kernel"),
    }
