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
import os
import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

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

_ALLOWED_TAGS = {"p", "br", "ul", "ol", "li", "strong", "em", "b", "i"}
_DROPPED_TAGS = {"script", "style", "iframe", "object", "embed", "svg", "math", "noscript"}
_STRIPE_CHECKOUT_NETLOCS = {"checkout.stripe.com", "checkout.stripe.com:443"}
_STRIPE_CHECKOUT_PATH = re.compile(r"/c/pay/[A-Za-z0-9_-]+$")
_STRIPE_SESSION_ID = re.compile(r"cs_[A-Za-z0-9_-]{4,200}$")


def _attr(value: object) -> str:
    return html.escape(str(value), quote=True)


class _DescriptionHTML(HTMLParser):
    """Allow a small set of tags and no attributes. Drop script-like bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _DROPPED_TAGS:
            self._skip += 1
            return
        if self._skip or tag not in _ALLOWED_TAGS:
            return
        self._parts.append("<br>" if tag == "br" else f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _DROPPED_TAGS:
            if self._skip:
                self._skip -= 1
            return
        if self._skip or tag not in _ALLOWED_TAGS or tag == "br":
            return
        self._parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._parts.append(html.escape(data, quote=True))

    def render(self) -> str:
        return "".join(self._parts)


def _safe_description(value: object) -> str:
    text = value if isinstance(value, str) else ""
    parser = _DescriptionHTML()
    try:
        parser.feed(text)
        parser.close()
    except Exception:
        return html.escape(text, quote=True)
    return parser.render()


def _utm_query(params: dict) -> str:
    utm = {k: v for k, v in params.items() if isinstance(k, str) and k.startswith("utm_") and isinstance(v, str)}
    return urlencode(utm) if utm else ""


def _public_base():
    raw = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").strip()
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
        return None
    if any(ch in parts.netloc for ch in "\\@ \t\r\n"):
        return None
    return parts


def _safe_checkout_target(value: object, *, dry_run: bool, brand_id: str, product_id: str) -> str | None:
    """Return a rebuilt redirect target, or None.

    Dry-run redirects are rebuilt from the local allowlisted base. Live
    redirects are rebuilt from the provider session identifier; the provider's
    returned URL is never used as a redirect authority.
    """
    if dry_run:
        if not isinstance(value, str) or not value or any(ch in value for ch in "\r\n\t\\"):
            return None
        parts = urlsplit(value)
        if parts.username or parts.password or parts.fragment:
            return None
        netloc = parts.netloc
        if not netloc or any(ch in netloc for ch in "\\@ "):
            return None
        base = _public_base()
        expected_path = f"/s/{brand_id}/{product_id}"
        if (
            base is None
            or parts.scheme != base.scheme
            or netloc.lower() != base.netloc.lower()
            or parts.path != expected_path
            or parts.query != "purchased=1"
            or "//" in parts.path
        ):
            return None
        return f"{base.scheme}://{base.netloc}{expected_path}?purchased=1"
    if not isinstance(value, str) or not _STRIPE_SESSION_ID.fullmatch(value):
        return None
    return f"https://checkout.stripe.com/c/pay/{value}"


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
        f'<a class="card" href="/s/{_attr(brand_id)}/{_attr(e.product_id)}">'
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
    checkout_href = f"/s/{_attr(brand_id)}/{_attr(product_id)}/checkout"
    if utm:
        checkout_href = f"{checkout_href}?{html.escape(utm, quote=True)}"

    if entry.stock_ok:
        cta = f'<a class="buy" href="{checkout_href}">Buy now — ${entry.retail_price:.2f}</a>'
    else:
        cta = '<div class="oos">Temporarily out of stock</div>'

    body = (
        f"<header><div class='brand'><a href='/s/{_attr(brand_id)}' style='color:inherit;"
        f"text-decoration:none'>{html.escape(brand.name)}</a></div>"
        f"<div class='tagline'>{html.escape(brand.tagline)}</div></header>"
        f"<main><h1>{html.escape(entry.title)}</h1>"
        f"<div class='price'>${entry.retail_price:.2f}</div>"
        f"{_safe_description(entry.description_html)}"
        f"<ul>{bullets}</ul>{cta}</main>"
        f"<footer>{html.escape(brand.name)} — ships direct from our fulfillment partners</footer>"
    )
    return HTMLResponse(f"<style>{_PAGE_STYLE}</style>{body}")


@router.get("/s/{brand_id}/{product_id}/checkout")
def start_checkout(brand_id: str, product_id: str, request: Request):
    """Create a Stripe Checkout Session and redirect the buyer to it.

    The redirect target is informational only — actual order fulfillment
    fires exclusively from the signed checkout.session.completed webhook
    (api/routes/webhooks.py), never from this request completing.
    """
    from backend.commerce.checkout import create_checkout_session

    utm = {k: v for k, v in request.query_params.items() if k.startswith("utm_")}
    result = create_checkout_session(brand_id, product_id, qty=1, utm=utm)
    if result.get("status") != "ok":
        return HTMLResponse(
            f"<h1>Checkout unavailable</h1><p>{html.escape(str(result.get('error', '')))}</p>",
            status_code=409,
        )
    dry_run = bool(result.get("dry_run"))
    target = _safe_checkout_target(
        result.get("url") if dry_run else result.get("session_id"),
        dry_run=dry_run,
        brand_id=brand_id,
        product_id=product_id,
    )
    if target is None:
        return HTMLResponse("<h1>Checkout unavailable</h1>", status_code=409)

    # Validate the final redirect immediately before handing it to Starlette.
    # The builder above reconstructs the target, but this second guard keeps
    # the redirect sink independent of route/provider taint and documents the
    # only two allowed URL contracts.
    target_parts = urlsplit(target)
    if dry_run:
        base = _public_base()
        safe_target = (
            base is not None
            and target_parts.scheme == base.scheme
            and target_parts.netloc.lower() == base.netloc.lower()
            and not target_parts.username
            and not target_parts.password
            and not target_parts.fragment
            and target_parts.query == "purchased=1"
        )
    else:
        safe_target = (
            target_parts.scheme == "https"
            and target_parts.netloc == "checkout.stripe.com"
            and not target_parts.username
            and not target_parts.password
            and not target_parts.query
            and not target_parts.fragment
            and _STRIPE_CHECKOUT_PATH.fullmatch(target_parts.path) is not None
        )
    if not safe_target:
        return HTMLResponse("<h1>Checkout unavailable</h1>", status_code=409)
    return RedirectResponse(url=target, status_code=303)
