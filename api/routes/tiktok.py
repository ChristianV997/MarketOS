"""api.routes.tiktok — launch, ROAS reporting, and anomaly check/act for TikTok campaigns."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


def _live_action_denial(
    action: str,
    error: str,
    *,
    response_fields: dict | None = None,
) -> JSONResponse:
    """Fail closed when a route would leave the offline simulation path."""
    try:
        from evaluation.companyos.approval_ledger import (
            SIMULATION_STATUSES,
            simulate_action,
        )

        simulation = simulate_action(action)
        policy_status = simulation.result
        if not isinstance(policy_status, str) or policy_status not in SIMULATION_STATUSES:
            policy_status = "unavailable"
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "error": "approval_policy_unavailable"},
        )

    # The Approval Ledger is offline policy evidence, never a live grant.
    content = {
        "status": "blocked",
        "error": error,
        "approval_status": policy_status,
    }
    content.update(response_fields or {})
    return JSONResponse(status_code=403, content=content)


@router.post("/tiktok/launch")
def tiktok_launch(product: str, phase: str = "EXPLORE"):
    """Launch a TikTok campaign from the best playbook for this product.
    The route only permits the adapter's no-network dry-run mode.
    """
    try:
        from backend.integrations import tiktok_ads

        # This flag identifies simulation mode; false is never approval.
        if tiktok_ads._DRY_RUN is not True:
            return _live_action_denial("launch_ad", "live_action_not_approved")

        from core.content.playbook import playbook_memory
        launch_from_playbook = tiktok_ads.launch_from_playbook

        pb = playbook_memory.get(product)
        if not pb:
            return {"status": "error", "reason": "no_playbook", "product": product}
        return launch_from_playbook(vars(pb), phase=phase)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "error": "launch_unavailable"},
        )


@router.get("/tiktok/roas")
def tiktok_roas_report():
    """Fetch latest ROAS from TikTok reporting API (or simulated in dry-run)."""
    try:
        from backend.integrations import tiktok_ads

        if tiktok_ads._DRY_RUN is not True:
            return _live_action_denial(
                "provider_call",
                "provider_call_not_approved",
                response_fields={"roas": {}, "campaign_count": 0},
            )

        # Real: pull active campaign IDs from portfolio engine
        try:
            from backend.decision.portfolio_engine import top_products
            products = top_products(n=10)
            cids = [str(p.get("product_id", "")) for p in products if p.get("product_id")]
        except Exception:
            cids = []
        if not cids:
            cids = ["demo_campaign"]
        roas_map = tiktok_ads.fetch_roas(cids)
        return {"roas": roas_map, "campaign_count": len(cids), "dry_run": True}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "error": "reporting_unavailable",
                "roas": {},
                "campaign_count": 0,
            },
        )


@router.post("/tiktok/check")
def tiktok_check_and_act(campaign_id: str, spend: float, budget: float, roas: float):
    """Run anomaly check on a campaign: kill if overspend+bad ROAS, scale if win streak."""
    try:
        from backend.integrations import tiktok_ads

        if tiktok_ads._DRY_RUN is not True:
            return _live_action_denial("launch_ad", "live_action_not_approved")

        action = tiktok_ads.check_and_act(campaign_id, spend, budget, roas)
        return {"campaign_id": campaign_id, "action": action, "dry_run": True}
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "error": "check_unavailable"},
        )


__all__ = ["router"]
