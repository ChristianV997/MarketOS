"""api.onboarding — Customer onboarding flow and setup wizard.

Guides new customers through:
1. Store setup (business info)
2. API credentials (Meta, TikTok, Shopify)
3. First product discovery and validation
4. Campaign launch and monitoring
"""
import logging
from typing import Any, Optional
from pydantic import BaseModel

from fastapi import APIRouter, HTTPException, Body

_log = logging.getLogger(__name__)

router = APIRouter()


# Data models for onboarding state
class StoreInfo(BaseModel):
    """Initial store information."""
    business_name: str
    store_type: str  # "shopify", "generic", "printful"
    country: str = "US"
    budget_daily: float = 50.0  # Starting daily budget


class OnboardingState(BaseModel):
    """Complete onboarding state."""
    step: int  # 1=store, 2=credentials, 3=discovery, 4=launch
    store_info: Optional[StoreInfo] = None
    credentials_set: dict = {}  # {service: status}
    discovered_products: int = 0
    validated_products: int = 0
    launched_campaigns: int = 0


# In-memory state per session (for MVP)
_sessions: dict[str, OnboardingState] = {}


@router.post("/start")
async def start_onboarding() -> dict:
    """Start a new onboarding session.

    Returns session_id and current step instructions.
    """
    import uuid
    session_id = str(uuid.uuid4())
    _sessions[session_id] = OnboardingState(step=1)
    _log.info("onboarding_started session=%s", session_id)

    return {
        "status": "ok",
        "session_id": session_id,
        "step": 1,
        "current_step": "Store Setup",
        "instructions": [
            "Enter your business name",
            "Select your store type (Shopify/Generic/Printful)",
            "Set your starting daily budget",
        ],
    }


@router.get("/step/{session_id}")
async def get_onboarding_step(session_id: str) -> dict:
    """Get current onboarding step and instructions."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    steps = {
        1: {
            "name": "Store Setup",
            "description": "Tell us about your store",
            "fields": ["business_name", "store_type", "country", "budget_daily"],
        },
        2: {
            "name": "API Credentials",
            "description": "Connect your ad accounts and store",
            "fields": ["meta", "tiktok", "shopify"],
        },
        3: {
            "name": "Product Discovery",
            "description": "Find products to sell",
            "fields": ["category", "keywords", "price_range"],
        },
        4: {
            "name": "Launch & Monitor",
            "description": "Start campaigns and watch metrics",
            "fields": ["review_results", "launch_campaigns"],
        },
    }

    current = steps.get(state.step, steps[1])

    return {
        "status": "ok",
        "session_id": session_id,
        "step": state.step,
        "step_name": current["name"],
        "description": current["description"],
        "instructions": current,
        "progress": {
            "total_steps": 4,
            "current_step": state.step,
            "percent_complete": int((state.step / 4) * 100),
        },
    }


@router.post("/step/1/store-info")
async def set_store_info(
    session_id: str = Body(...),
    store_info: dict = Body(...),
) -> dict:
    """Submit store information."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    if state.step != 1:
        raise HTTPException(status_code=400, detail="Not on step 1")

    try:
        store = StoreInfo(**store_info)
        state.store_info = store
        state.step = 2
        _log.info("onboarding_store_set session=%s business=%s", session_id, store.business_name)

        return {
            "status": "ok",
            "message": f"Welcome, {store.business_name}!",
            "next_step": 2,
            "next_step_name": "API Credentials",
        }
    except Exception as exc:
        _log.error("failed_to_set_store_info session=%s error=%s", session_id, exc)
        raise HTTPException(status_code=400, detail=f"Invalid store info: {exc}")


@router.post("/step/2/verify-credential")
async def verify_and_set_credential(
    session_id: str = Body(...),
    service: str = Body(...),
    credential_key: str = Body(...),
    credential_value: str = Body(...),
) -> dict:
    """Verify and store a single credential."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    if state.step != 2:
        raise HTTPException(status_code=400, detail="Not on step 2")

    service = service.lower()
    try:
        from backend.config import set_credential
        from api.credentials_setup import test_credentials

        # Try to set the credential
        set_credential(credential_key, credential_value)
        _log.info("credential_set session=%s service=%s key=%s", session_id, service, credential_key)

        # Test if it works
        test_result = await test_credentials(service)

        # Track status
        if "credentials_set" not in state.__dict__:
            state.credentials_set = {}
        state.credentials_set[service] = test_result.get("status")

        return {
            "status": "ok",
            "message": f"Credential verified for {service}",
            "service": service,
            "test_result": test_result,
            "progress": {
                "services_configured": len([s for s, status in state.credentials_set.items()
                                           if status != "dry_run"]),
                "services_total": 3,
            },
        }
    except Exception as exc:
        _log.error("failed_to_verify_credential session=%s service=%s error=%s",
                  session_id, service, exc)
        raise HTTPException(status_code=400, detail=f"Failed to verify credential: {exc}")


@router.post("/step/{session_id}/complete")
async def complete_credentials(session_id: str) -> dict:
    """Mark current step as complete and advance."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    current_step = state.step
    next_step_map = {
        1: (2, "API Credentials"),
        2: (3, "Product Discovery"),
        3: (4, "Launch & Monitor"),
    }

    if current_step not in next_step_map:
        raise HTTPException(status_code=400, detail=f"Cannot advance from step {current_step}")

    next_step, next_name = next_step_map[current_step]
    state.step = next_step
    _log.info("onboarding_step_complete session=%s step=%d->%d", session_id, current_step, next_step)

    return {
        "status": "ok",
        "message": f"Step {current_step} complete!",
        "next_step": next_step,
        "next_step_name": next_name,
    }


@router.post("/step/3/discover")
async def discover_products(
    session_id: str = Body(...),
    category: str = Body(...),
    max_products: int = Body(default=5),
) -> dict:
    """Discover products in a category."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    if state.step != 3:
        raise HTTPException(status_code=400, detail="Not on step 3")

    try:
        from backend.discovery import discover_products as discover_fn

        products = discover_fn(
            category=category,
            limit=max_products,
            score_threshold=0.6,
        )

        state.discovered_products = len(products)
        _log.info("onboarding_discover session=%s category=%s count=%d",
                 session_id, category, len(products))

        return {
            "status": "ok",
            "products": products[:max_products],
            "count": len(products),
            "instructions": "Review these products and select one to validate",
        }
    except Exception as exc:
        _log.error("failed_to_discover_products session=%s error=%s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Discovery failed: {exc}")


@router.post("/step/3/validate-product")
async def validate_selected_product(
    session_id: str = Body(...),
    product_id: str = Body(...),
) -> dict:
    """Validate and stage a single product for launch."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    if state.step != 3:
        raise HTTPException(status_code=400, detail="Not on step 3")

    try:
        from backend.validation import validate_product

        result = validate_product(product_id)

        if result.get("valid"):
            state.validated_products += 1
            _log.info("onboarding_validate session=%s product=%s valid=true",
                     session_id, product_id)

            return {
                "status": "ok",
                "message": "Product validated!",
                "product": result,
                "ready_to_launch": True,
            }
        else:
            return {
                "status": "warning",
                "message": "Product validation found issues",
                "product": result,
                "ready_to_launch": False,
            }
    except Exception as exc:
        _log.error("failed_to_validate_product session=%s product=%s error=%s",
                  session_id, product_id, exc)
        raise HTTPException(status_code=500, detail=f"Validation failed: {exc}")


@router.post("/step/4/launch")
async def launch_campaigns(
    session_id: str = Body(...),
    product_ids: list[str] = Body(...),
) -> dict:
    """Launch campaigns for validated products."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    if state.step not in [3, 4]:
        raise HTTPException(status_code=400, detail="Not ready to launch")

    if not state.store_info:
        raise HTTPException(status_code=400, detail="Store info not set")

    try:
        from backend.dropship import run_dropship_cycle

        result = run_dropship_cycle(
            max_products=len(product_ids),
            budget_daily=state.store_info.budget_daily,
        )

        state.launched_campaigns = result.get("launched", 0)
        state.step = 4
        _log.info("onboarding_launch session=%s campaigns=%d", session_id, state.launched_campaigns)

        return {
            "status": "ok" if state.launched_campaigns > 0 else "warning",
            "message": f"Launched {state.launched_campaigns} campaigns!",
            "campaigns": result.get("campaign_ids", []),
            "next_steps": [
                "Monitor campaign performance in your dashboard",
                "Adjust budgets based on ROAS",
                "Add more products to expand reach",
            ],
        }
    except Exception as exc:
        _log.error("failed_to_launch_campaigns session=%s error=%s", session_id, exc)
        raise HTTPException(status_code=500, detail=f"Launch failed: {exc}")


@router.get("/step/4/summary/{session_id}")
async def onboarding_summary(session_id: str) -> dict:
    """Get final onboarding summary and next steps."""
    state = _sessions.get(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "status": "ok",
        "session_id": session_id,
        "completion": {
            "store_name": state.store_info.business_name if state.store_info else "Unknown",
            "credentials_set": len(state.credentials_set),
            "products_discovered": state.discovered_products,
            "products_validated": state.validated_products,
            "campaigns_launched": state.launched_campaigns,
        },
        "dashboard_url": "/dashboard",
        "next_steps": [
            "Monitor live campaign performance",
            "Review profitability metrics",
            "Scale winning products",
            "Add more products to portfolio",
        ],
    }


__all__ = ["router"]
