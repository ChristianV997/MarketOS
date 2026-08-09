"""backend.commerce.storefront — storefront adapter dispatch.

Two bindings per Brand.storefront:
  "landing"  (default) — MarketOS's own FastAPI-served landing pages; product
             pages live entirely in the catalog and render at
             {PUBLIC_BASE_URL}/s/{brand_id}/{product_id}. Zero external
             dependencies, zero per-store fees; checkout via Stripe (Phase C).
  "shopify"  — wraps backend.creation.store_builder against a per-brand
             Shopify store. Per-brand credentials use the env pattern
             BRAND_<BRAND_ID>_SHOPIFY_STORE_URL / _SHOPIFY_ACCESS_TOKEN,
             falling back to the global SHOPIFY_* pair.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from backend.commerce.brands import Brand
from backend.commerce.catalog import (
    STATUS_LIVE,
    CatalogEntry,
    product_catalog,
    product_slug,
)

_log = logging.getLogger(__name__)


def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


class Storefront(Protocol):
    def create_product(self, brand: Brand, listing: dict, price: float,
                       supplier: dict | None = None) -> dict[str, Any]: ...
    def update_product(self, brand: Brand, product_id: str, *,
                       price: float | None = None,
                       status: str | None = None,
                       stock_ok: bool | None = None) -> dict[str, Any]: ...


class LandingStorefront:
    """Product pages served by our own API — the catalog IS the store."""

    def create_product(self, brand: Brand, listing: dict, price: float,
                       supplier: dict | None = None) -> dict[str, Any]:
        supplier = supplier or {}
        product_id = product_slug(listing.get("title", "product"))
        url = f"{_public_base_url()}/s/{brand.brand_id}/{product_id}"
        entry = CatalogEntry(
            product_id=product_id,
            brand_id=brand.brand_id,
            title=listing.get("title", product_id),
            retail_price=float(price),
            supplier=str(supplier.get("supplier", "")),
            supplier_product_id=str(supplier.get("product_id", "")),
            landed_cost=float(supplier.get("landed_cost", 0.0) or 0.0),
            status=STATUS_LIVE,
            page_url=url,
            description_html=listing.get("description", ""),
            bullets=list(listing.get("bullets", [])),
        )
        product_catalog.register(entry)
        return {"status": "ok", "product_id": product_id, "url": url, "dry_run": False}

    def update_product(self, brand: Brand, product_id: str, *,
                       price: float | None = None,
                       status: str | None = None,
                       stock_ok: bool | None = None) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        if price is not None:
            fields["retail_price"] = float(price)
        if status is not None:
            fields["status"] = status
        if stock_ok is not None:
            fields["stock_ok"] = bool(stock_ok)
        entry = product_catalog.update(product_id, **fields)
        if entry is None:
            return {"status": "error", "error": "unknown_product", "product_id": product_id}
        return {"status": "ok", "product_id": product_id, "dry_run": False}


class ShopifyStorefront:
    """Wraps the existing store_builder against a (possibly per-brand) Shopify store."""

    def _with_brand_creds(self, brand: Brand):
        """Context manager applying per-brand Shopify credentials if configured."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            prefix = f"BRAND_{brand.brand_id.upper().replace('-', '_')}_"
            overrides = {}
            for key in ("SHOPIFY_STORE_URL", "SHOPIFY_ACCESS_TOKEN"):
                val = os.getenv(prefix + key)
                if val:
                    overrides[key] = (os.environ.get(key), val)
                    os.environ[key] = val
            try:
                yield
            finally:
                for key, (old, _new) in overrides.items():
                    if old is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = old

        return _ctx()

    def create_product(self, brand: Brand, listing: dict, price: float,
                       supplier: dict | None = None) -> dict[str, Any]:
        from backend.creation.store_builder import create_product_page

        supplier = supplier or {}
        with self._with_brand_creds(brand):
            page = create_product_page(
                title=listing.get("title", ""),
                description_html=listing.get("description", ""),
                price=price,
                sku=str(supplier.get("product_id", "")),
                vendor=brand.name,
                tags=["dropship", "auto-generated", brand.brand_id],
            )
        if page.get("status") == "ok":
            # Mirror into the catalog so inventory/orders see Shopify products
            # too. external_id carries Shopify's OWN product id (numeric, or
            # a dry_* id) — required to look the product back up for updates,
            # since it's distinct from our slug-based product_id.
            product_id = product_slug(listing.get("title", "product"))
            product_catalog.register(CatalogEntry(
                product_id=product_id,
                brand_id=brand.brand_id,
                title=listing.get("title", product_id),
                retail_price=float(price),
                supplier=str(supplier.get("supplier", "")),
                supplier_product_id=str(supplier.get("product_id", "")),
                landed_cost=float(supplier.get("landed_cost", 0.0) or 0.0),
                status=STATUS_LIVE,
                page_url=page.get("url", ""),
                description_html=listing.get("description", ""),
                bullets=list(listing.get("bullets", [])),
                external_id=str(page.get("product_id", "")),
            ))
            page["product_id_catalog"] = product_id
        return page

    def update_product(self, brand: Brand, product_id: str, *,
                       price: float | None = None,
                       status: str | None = None,
                       stock_ok: bool | None = None) -> dict[str, Any]:
        from backend.creation.store_builder import update_product_page

        entry = product_catalog.get(product_id)
        if entry is None:
            return {"status": "error", "error": "unknown_product", "product_id": product_id}

        result: dict[str, Any] = {"status": "ok", "product_id": product_id, "dry_run": True}
        if entry.external_id and (price is not None or status is not None):
            with self._with_brand_creds(brand):
                result = update_product_page(
                    entry.external_id, price=price,
                    status=status if status in ("live", "draft") else None,
                )
            if result.get("status") != "ok":
                return result

        fields: dict[str, Any] = {}
        if price is not None:
            fields["retail_price"] = float(price)
        if status is not None:
            fields["status"] = status
        if stock_ok is not None:
            fields["stock_ok"] = bool(stock_ok)
        if fields:
            product_catalog.update(product_id, **fields)
        return {"status": "ok", "product_id": product_id,
                "dry_run": result.get("dry_run", True)}


_ADAPTERS: dict[str, Any] = {}


def get_storefront(brand: Brand) -> Storefront:
    """Return the storefront adapter for *brand* (cached per binding type)."""
    binding = brand.storefront if brand.storefront in ("landing", "shopify") else "landing"
    if binding not in _ADAPTERS:
        _ADAPTERS[binding] = (
            ShopifyStorefront() if binding == "shopify" else LandingStorefront()
        )
    return _ADAPTERS[binding]
