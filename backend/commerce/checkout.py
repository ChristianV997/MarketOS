"""backend.commerce.checkout — Stripe Checkout Session creation.

The landing page's Buy button lands here: a Checkout Session is created
with brand/product/utm metadata (so the completed-payment webhook can
attribute and route the order), and the customer is redirected to Stripe's
hosted payment page. Shipping address collection is enabled — the address
is what gets forwarded to the dropship supplier in Phase D.

Fulfillment is NEVER triggered from the success redirect — only from the
signed checkout.session.completed webhook (api/routes/webhooks.py).

Dry-run (CHECKOUT_DRY_RUN=true, the default, or STRIPE_SECRET_KEY unset):
returns a deterministic dry session whose "url" points at the local
success path, so the full order loop is rehearsable offline.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_SESSION_SEQ = 0


def _dry_run() -> bool:
    if os.getenv("CHECKOUT_DRY_RUN", "true").lower() != "false":
        return True
    return not os.getenv("STRIPE_SECRET_KEY")


def _next_dry_session_id(seed: str) -> str:
    global _SESSION_SEQ
    _SESSION_SEQ += 1
    stem = hashlib.md5(seed.encode()).hexdigest()[:10]
    return f"dry_cs_{stem}_{_SESSION_SEQ}"


def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")


def create_checkout_session(
    brand_id: str,
    product_id: str,
    qty: int = 1,
    utm: dict | None = None,
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for one catalog product.

    Returns {status, session_id, url, dry_run} — url is where the buyer
    should be redirected. Unknown/paused/out-of-stock products error.
    """
    from backend.commerce.brands import brand_registry
    from backend.commerce.catalog import STATUS_LIVE, product_catalog

    brand = brand_registry.get(brand_id)
    entry = product_catalog.get(product_id)
    if brand is None or entry is None or entry.brand_id != brand_id:
        return {"status": "error", "error": "unknown_product", "dry_run": _dry_run()}
    if entry.status != STATUS_LIVE or not entry.stock_ok:
        return {"status": "error", "error": "unavailable", "dry_run": _dry_run()}

    qty = max(1, int(qty))
    utm = {k: str(v) for k, v in (utm or {}).items() if k.startswith("utm_")}
    base = _public_base_url()
    success_url = f"{base}/s/{brand_id}/{product_id}?purchased=1"
    cancel_url = f"{base}/s/{brand_id}/{product_id}"

    if _dry_run():
        session_id = _next_dry_session_id(f"{brand_id}:{product_id}")
        _log.info("checkout_dry_session id=%s product=%s qty=%d amount=%.2f",
                  session_id, product_id, qty, entry.retail_price * qty)
        result = {"status": "ok", "session_id": session_id,
                  "url": success_url, "dry_run": True}
    else:
        try:
            import stripe
            metadata = {"brand_id": brand_id, "product_id": product_id, "qty": str(qty)}
            metadata.update({k: v[:100] for k, v in utm.items()})
            session = stripe.checkout.Session.create(
                mode="payment",
                success_url=success_url,
                cancel_url=cancel_url,
                shipping_address_collection={"allowed_countries": ["US"]},
                line_items=[{
                    "quantity": qty,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": int(round(entry.retail_price * 100)),
                        "product_data": {"name": entry.title},
                    },
                }],
                metadata=metadata,
                api_key=os.environ["STRIPE_SECRET_KEY"],
            )
            # Bracket access, not `.get()` — a real stripe.checkout.Session
            # object (unlike a plain dict) routes `.get` through __getattr__
            # to a key lookup and raises AttributeError.
            result = {"status": "ok", "session_id": str(session["id"] if "id" in session else ""),
                      "url": str(session["url"] if "url" in session else ""), "dry_run": False}
        except Exception as exc:
            _log.exception("checkout_session_failed product=%s", product_id)
            return {"status": "error", "error": str(exc), "dry_run": False}

    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("checkout"), "checkout_session_created",
            workflow="order_intake", step="checkout_session",
            data={"session_id": result["session_id"], "brand_id": brand_id,
                  "product_id": product_id, "qty": qty,
                  "amount": round(entry.retail_price * qty, 2),
                  "utm": utm, "dry_run": result["dry_run"]},
        )
    except Exception:
        _log.warning("checkout_session_journal_failed session_id=%s product=%s",
                     result.get("session_id", ""), product_id, exc_info=True)

    return result
