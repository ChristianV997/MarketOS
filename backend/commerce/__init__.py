"""backend.commerce — brand registry, product catalog, and storefront layer.

The commerce back-half of the dropship spine: a handful of brand/category
storefronts (landing pages by default, Shopify optional per brand), their
product catalogs, and the storefront adapters that create/update product
pages on whichever backend a brand is bound to.

Public surface:
    brand_registry            singleton — Brand CRUD + category routing
    product_catalog           singleton — per-brand catalog entries
    get_storefront(brand)     storefront adapter dispatch
"""
from backend.commerce.brands import Brand, brand_registry
from backend.commerce.catalog import CatalogEntry, product_catalog
from backend.commerce.storefront import get_storefront

__all__ = [
    "Brand",
    "brand_registry",
    "CatalogEntry",
    "product_catalog",
    "get_storefront",
]
