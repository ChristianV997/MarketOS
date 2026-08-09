"""backend.creation — store + creative generation (Pipeline 3 of the
dropship spine: Discover → Validate → Create → Launch → Optimize).

Public surface:
    generate_listing(product, price)      → title/description/bullets
    generate_ad_copy(product, platform)   → hooks/angles/headlines/ctas
    create_product_page(...)              → Shopify product (dry-run safe)
    build_product(verdict)                → listing + copy + store page in one call
"""
from backend.creation.creative_generator import generate_listing, generate_ad_copy
from backend.creation.store_builder import create_product_page, build_product

__all__ = [
    "generate_listing",
    "generate_ad_copy",
    "create_product_page",
    "build_product",
]
