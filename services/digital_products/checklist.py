"""services.digital_products.checklist — build_launch_checklist."""
from __future__ import annotations

from typing import Any

from .schemas import DigitalOffer, DigitalProductValidation, FunnelPlan


def build_launch_checklist(
    offer: DigitalOffer, funnel: FunnelPlan, validation: DigitalProductValidation,
) -> list[dict[str, Any]]:
    """Never raises."""
    return [
        {"item": "offer name, target customer, and transformation promised are defined", "done": bool(offer.offer_name and offer.target_customer)},
        {"item": "price is set", "done": offer.price > 0},
        {"item": "lead magnet and funnel steps are defined", "done": bool(funnel.funnel_steps)},
        {"item": "sales page structure drafted", "done": bool(funnel.sales_page_structure)},
        {"item": "pre-launch validation test run", "done": bool(validation.validation_test)},
        {"item": "validation verdict is viable or strong before spending on paid traffic", "done": validation.verdict in ("viable", "strong")},
        {"item": "payment processing configured (Stripe or equivalent)", "done": False},
        {"item": "delivery mechanism ready (download link / course platform / calendar booking)", "done": False},
        {"item": "analytics/tracking configured on the sales page and checkout", "done": False},
    ]
