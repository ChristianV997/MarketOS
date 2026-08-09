"""services.digital_products — turn MarketOS artifacts into a sellable
digital-product offer/funnel/validation plan."""
from .checklist import build_launch_checklist
from .content_plan import generate_content_plan
from .funnel import build_funnel_plan
from .offer import create_digital_offer
from .plan import build_digital_product_plan
from .report import render_digital_product_markdown
from .schemas import PRODUCT_TYPES, VALIDATION_VERDICTS, DigitalProductPlan
from .validation import validate_digital_product

__all__ = [
    "create_digital_offer",
    "build_funnel_plan",
    "validate_digital_product",
    "generate_content_plan",
    "build_launch_checklist",
    "build_digital_product_plan",
    "render_digital_product_markdown",
    "DigitalProductPlan",
    "PRODUCT_TYPES",
    "VALIDATION_VERDICTS",
]
