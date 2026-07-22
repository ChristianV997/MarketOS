"""backend.creation.store_builder — Shopify product-page automation.

Creates the store side of a validated product: product page with listing
copy, price, and supplier SKU.  Dry-run by default (STORE_DRY_RUN=true) so
the pipeline runs end-to-end without a live shop; production activation
needs STORE_DRY_RUN=false plus the same SHOPIFY_STORE_URL /
SHOPIFY_ACCESS_TOKEN credentials backend.integrations.shopify_client uses.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_DRY_RUN = os.getenv("STORE_DRY_RUN", "true").lower() != "false"

# Monotonic counter so two dry-run pages created in the same second never
# collide (same defect class as the tiktok dry-id collision fixed in Round 2).
_dry_seq = 0


def _next_dry_id(product: str) -> str:
    global _dry_seq
    _dry_seq += 1
    stem = hashlib.md5(product.encode()).hexdigest()[:8]
    return f"dryprod_{stem}_{_dry_seq}"


def create_product_page(
    title: str,
    description_html: str,
    price: float,
    sku: str = "",
    vendor: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create a Shopify product. Returns {status, product_id, url, dry_run}."""
    if _DRY_RUN:
        pid = _next_dry_id(title)
        _log.info("store_dry_run product_created id=%s title=%r price=%s", pid, title, price)
        return {
            "status": "ok",
            "product_id": pid,
            "url": f"https://dry-run.local/products/{pid}",
            "dry_run": True,
        }
    try:
        from backend.integrations.shopify_client import init_shopify
        import shopify
        if not init_shopify():
            return {"status": "error", "error": "shopify_not_configured", "dry_run": False}
        product = shopify.Product()
        product.title = title
        product.body_html = description_html
        product.vendor = vendor
        product.product_type = "Dropship"
        product.tags = ",".join(tags or [])
        variant = shopify.Variant({"price": price, "sku": sku})
        product.variants = [variant]
        product.save()
        if product.errors.errors:
            return {"status": "error", "error": str(product.errors.errors), "dry_run": False}
        shop_url = os.getenv("SHOPIFY_STORE_URL", "")
        return {
            "status": "ok",
            "product_id": str(product.id),
            "url": f"https://{shop_url}/products/{product.handle}",
            "dry_run": False,
        }
    except Exception as exc:
        _log.exception("store_product_create_failed title=%r", title)
        return {"status": "error", "error": str(exc), "dry_run": False}


def build_product(verdict: dict[str, Any], brand: Any = None) -> dict[str, Any]:
    """Create listing + ad copy + store page from a validation verdict.

    Takes the output of backend.validation.validate_product (must be
    ready_for_creation) and returns everything Pipeline 4 needs to launch:

        {status, product, brand_id, page: {...}, listing: {...}, ad_copy: {...}}

    Brand routing (Phase A): the product is assigned to a brand (resolved
    by category via the brand registry when *brand* is None) and created
    through that brand's storefront adapter — a MarketOS landing page by
    default, or the brand's Shopify store when so bound. Falls back to the
    legacy direct-Shopify path only if the commerce layer is unavailable.
    """
    product = verdict.get("product", "")
    if not verdict.get("ready_for_creation"):
        return {"status": "skipped", "reason": "not_validated", "product": product}

    from backend.creation.creative_generator import generate_listing, generate_ad_copy

    price = float(verdict.get("retail_price") or verdict.get("suggested_price") or 0.0)
    supplier = verdict.get("supplier") or {}

    listing = generate_listing(
        product, price, supplier_days=int(supplier.get("fulfillment_days", 9))
    )

    brand_id = ""
    try:
        from backend.commerce.brands import brand_registry
        from backend.commerce.storefront import get_storefront

        if brand is None:
            brand = brand_registry.resolve_for_category(
                str(verdict.get("category", "general"))
            )
        brand_id = brand.brand_id
        page = get_storefront(brand).create_product(
            brand, listing, price, supplier=supplier,
        )
        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("commerce"), "brand_product_registered",
                workflow="commerce", step="catalog_register",
                data={"brand_id": brand_id, "product": product,
                      "price": price, "page_url": page.get("url", "")},
            )
        except Exception:
            pass
    except Exception:
        _log.debug("brand_routing_unavailable; using legacy store path", exc_info=True)
        page = create_product_page(
            title=listing["title"],
            description_html=listing["description"],
            price=price,
            sku=str(supplier.get("product_id", "")),
            vendor=str(supplier.get("supplier", "")),
            tags=["dropship", "auto-generated"],
        )

    if page.get("status") != "ok":
        return {"status": "error", "reason": "store_page_failed", "product": product,
                "error": page.get("error", "")}

    ad_copy = {
        "tiktok": generate_ad_copy(product, "tiktok"),
        "meta": generate_ad_copy(product, "meta"),
    }
    return {
        "status": "ok",
        "product": product,
        "brand_id": brand_id,
        "price": price,
        "page": page,
        "listing": listing,
        "ad_copy": ad_copy,
    }
