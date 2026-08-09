"""services.digital_products.offer — create_digital_offer."""
from __future__ import annotations

from .schemas import DigitalOffer


def create_digital_offer(
    offer_name: str, *, product_type: str = "playbook", target_customer: str = "",
    transformation_promised: str = "", price: float = 0.0,
) -> DigitalOffer:
    """Never raises. Unknown product_type is recorded as-is rather than
    rejected — callers can check `product_type in schemas.PRODUCT_TYPES`
    themselves if they need to enforce the closed set."""
    return DigitalOffer(
        offer_name=offer_name,
        product_type=product_type,
        target_customer=target_customer,
        transformation_promised=transformation_promised,
        price=max(0.0, price),
    )
