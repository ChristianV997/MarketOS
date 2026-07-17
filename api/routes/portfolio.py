"""api.routes.portfolio — portfolio allocations and ranked product opportunities."""
from __future__ import annotations

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/portfolio")
def portfolio():
    """ROAS-weighted budget allocation across active products/variants."""
    try:
        from backend.decision.portfolio_engine import get_allocations, top_products
        return {
            "allocations": get_allocations(),
            "top_products": top_products(n=5),
        }
    except Exception:
        return {"allocations": {}, "top_products": []}


@router.get("/opportunities")
def opportunities(limit: int = Query(default=20, ge=1, le=100)):
    """Ranked product opportunities from the live simulation layer.

    Returns the current top-N candidates scored by the simulation engine,
    enriched with:
      - simulation rank score and corrected ROAS prediction
      - playbook confidence and evidence count
      - calibration status (are predictions reliable for this product?)
      - suggested top hooks and angles from PatternStore

    Designed for operational decision-making: highest rank_score products
    are the best candidates for content generation and campaign launch.
    """
    try:
        from simulation.engine import simulation_engine
        from core.content.patterns import pattern_store
        from core.content.playbook import playbook_memory
        from simulation.calibration import calibration_store
        from core.signals import signal_engine

        signals = signal_engine.get()
        patterns = pattern_store.get_patterns()
        all_pbs  = {p.product: vars(p) for p in playbook_memory.all()}

        ranked = simulation_engine.score_signals(
            signals[:30],
            patterns=patterns,
            playbooks=all_pbs,
        )

        cal_summary = calibration_store.summary()
        by_product  = cal_summary.get("by_product", {})

        results = []
        for r in ranked[:limit]:
            pb = all_pbs.get(r.product, {})
            product_cal = by_product.get(r.product, {})
            results.append({
                "rank":              r.rank,
                "product":           r.product,
                "rank_score":        round(r.rank_score, 4),
                "predicted_roas":    round(r.predicted_roas, 4),
                "corrected_roas":    round(r.corrected_roas, 4),
                "predicted_ctr":     round(r.predicted_ctr, 4),
                "confidence":        round(r.confidence, 4),
                "risk_score":        round(r.risk_score, 4),
                # Playbook context
                "playbook_confidence": round(float(pb.get("confidence", 0.0)), 4),
                "evidence_count":      int(pb.get("evidence_count", 0)),
                "top_hooks":           pb.get("top_hooks", [])[:3],
                "top_angles":          pb.get("top_angles", [])[:3],
                # Calibration readiness
                "calibrated":          product_cal.get("n", 0) >= 5,
                "calibration_records": product_cal.get("n", 0),
                # Action priority: corrected_roas * confidence / (1 + risk)
                "action_priority": round(
                    r.corrected_roas * r.confidence / max(1.0 + r.risk_score, 0.01), 4
                ),
            })

        results.sort(key=lambda x: x["action_priority"], reverse=True)
        return {
            "count":        len(results),
            "calibrated":   cal_summary.get("ready", False),
            "top_hooks":    patterns.get("top_hooks", [])[:5],
            "top_angles":   patterns.get("top_angles", [])[:5],
            "opportunities": results,
        }
    except Exception as exc:
        return {"count": 0, "opportunities": [], "error": str(exc)}


__all__ = ["router"]
