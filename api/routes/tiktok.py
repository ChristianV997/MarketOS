"""api.routes.tiktok — launch, ROAS reporting, and anomaly check/act for TikTok campaigns."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/tiktok/launch")
def tiktok_launch(product: str, phase: str = "EXPLORE"):
    """Launch a TikTok campaign from the best playbook for this product.
    Safe: defaults to dry-run mode. Set TIKTOK_DRY_RUN=false to go live.
    """
    try:
        from backend.integrations.tiktok_ads import launch_from_playbook
        from core.content.playbook import playbook_memory
        pb = playbook_memory.get(product)
        if not pb:
            return {"status": "error", "reason": "no_playbook", "product": product}
        return launch_from_playbook(vars(pb), phase=phase)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


@router.get("/tiktok/roas")
def tiktok_roas_report():
    """Fetch latest ROAS from TikTok reporting API (or simulated in dry-run)."""
    try:
        from backend.integrations.tiktok_ads import fetch_roas
        # Real: pull active campaign IDs from portfolio engine
        try:
            from backend.decision.portfolio_engine import top_products
            products = top_products(n=10)
            cids = [str(p.get("product_id", "")) for p in products if p.get("product_id")]
        except Exception:
            cids = []
        if not cids:
            cids = ["demo_campaign"]
        roas_map = fetch_roas(cids)
        return {"roas": roas_map, "campaign_count": len(cids)}
    except Exception as exc:
        return {"error": str(exc)}


@router.post("/tiktok/check")
def tiktok_check_and_act(campaign_id: str, spend: float, budget: float, roas: float):
    """Run anomaly check on a campaign: kill if overspend+bad ROAS, scale if win streak."""
    try:
        from backend.integrations.tiktok_ads import check_and_act
        action = check_and_act(campaign_id, spend, budget, roas)
        return {"campaign_id": campaign_id, "action": action}
    except Exception as exc:
        return {"error": str(exc)}


__all__ = ["router"]
