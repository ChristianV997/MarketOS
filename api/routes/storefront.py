"""api.routes.storefront — public brand landing pages.

Serves the "landing" storefront binding: one page per catalog product at
GET /s/{brand_id}/{product_id}, plus a brand index at GET /s/{brand_id}.
Pages render from the ProductCatalog with the brand's identity; utm_*
query params are threaded into the checkout link so paid/organic traffic
stays attributable end-to-end (Phase C consumes them at checkout).

Plain f-string HTML — no template-engine dependency; pages are simple,
fast, and fully testable with TestClient offline.
"""
from __future__ import annotations

import html
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

_log = logging.getLogger(__name__)

router = APIRouter()

_PAGE_STYLE = """
  body{font-family:system-ui,sans-serif;margin:0;color:#1c2025;background:#fafaf8}
  main{max-width:760px;margin:0 auto;padding:32px 20px}
  header{padding:18px 20px;border-bottom:1px solid #e5e3dc;background:#fff}
  .brand{font-weight:700;font-size:18px;letter-spacing:.02em}
  .tagline{color:#6b7280;font-size:13px}
  h1{font-size:26px;margin:18px 0 6px}
  .price{font-size:22px;font-weight:700;color:#0e6f6f;margin:8px 0 16px}
  ul{padding-left:20px}li{margin-bottom:6px}
  .buy{display:inline-block;background:#0e6f6f;color:#fff;padding:12px 28px;
       border-radius:6px;text-decoration:none;font-weight:600;margin-top:14px}
  .oos{color:#b3392f;font-weight:600;margin-top:14px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:14px;margin-top:20px}
  .card{background:#fff;border:1px solid #e5e3dc;border-radius:8px;padding:14px;text-decoration:none;color:inherit}
  .card .t{font-weight:600;margin-bottom:4px}
  footer{color:#9aa3ad;font-size:12px;padding:26px 20px;text-align:center}
"""


def _utm_query(params: dict) -> str:
    utm = {k: v for k, v in params.items() if k.startswith("utm_")}
    return urlencode(utm) if utm else ""


@router.get("/s/{brand_id}", response_class=HTMLResponse)
def brand_page(brand_id: str) -> HTMLResponse:
    from backend.commerce.brands import brand_registry
    from backend.commerce.catalog import STATUS_LIVE, product_catalog

    brand = brand_registry.get(brand_id)
    if brand is None or not brand.active:
        return HTMLResponse("<h1>Store not found</h1>", status_code=404)

    entries = [e for e in product_catalog.for_brand(brand_id, status=STATUS_LIVE)
               if e.stock_ok]
    cards = "".join(
        f'<a class="card" href="/s/{brand_id}/{e.product_id}">'
        f'<div class="t">{html.escape(e.title)}</div>'
        f'<div class="price">${e.retail_price:.2f}</div></a>'
        for e in entries
    )
    body = (
        f"<header><div class='brand'>{html.escape(brand.name)}</div>"
        f"<div class='tagline'>{html.escape(brand.tagline)}</div></header>"
        f"<main><div class='grid'>{cards or '<p>New drops coming soon.</p>'}</div></main>"
        f"<footer>{html.escape(brand.name)}</footer>"
    )
    return HTMLResponse(f"<style>{_PAGE_STYLE}</style>{body}")


@router.get("/s/{brand_id}/{product_id}", response_class=HTMLResponse)
def product_page(brand_id: str, product_id: str, request: Request) -> HTMLResponse:
    from backend.commerce.brands import brand_registry
    from backend.commerce.catalog import STATUS_LIVE, product_catalog

    brand = brand_registry.get(brand_id)
    entry = product_catalog.get(product_id)
    if (brand is None or not brand.active or entry is None
            or entry.brand_id != brand_id or entry.status != STATUS_LIVE):
        return HTMLResponse("<h1>Product not found</h1>", status_code=404)

    bullets = "".join(f"<li>{html.escape(str(b))}</li>" for b in entry.bullets)
    utm = _utm_query(dict(request.query_params))
    checkout_href = f"/s/{brand_id}/{product_id}/checkout" + (f"?{utm}" if utm else "")

    if entry.stock_ok:
        cta = f'<a class="buy" href="{checkout_href}">Buy now — ${entry.retail_price:.2f}</a>'
    else:
        cta = '<div class="oos">Temporarily out of stock</div>'

    body = (
        f"<header><div class='brand'><a href='/s/{brand_id}' style='color:inherit;"
        f"text-decoration:none'>{html.escape(brand.name)}</a></div>"
        f"<div class='tagline'>{html.escape(brand.tagline)}</div></header>"
        f"<main><h1>{html.escape(entry.title)}</h1>"
        f"<div class='price'>${entry.retail_price:.2f}</div>"
        f"{entry.description_html}"
        f"<ul>{bullets}</ul>{cta}</main>"
        f"<footer>{html.escape(brand.name)} — ships direct from our fulfillment partners</footer>"
    )
    return HTMLResponse(f"<style>{_PAGE_STYLE}</style>{body}")
