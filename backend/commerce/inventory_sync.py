"""backend.commerce.inventory_sync — keep brand catalogs current.

The catalog is created once by build_product(); nothing since Phase A
re-checked whether a supplier's cost drifted, whether they went out of
stock, or whether the retail price still hits the target margin. This
module closes that gap: for each brand's live catalog entries, re-quote
the bound supplier, recompute retail price on meaningful cost drift, and
pause listings whose supplier can no longer fulfill them.

Always journals shadow_inventory_sync (legacy price/status vs proposed);
only mutates the storefront when INVENTORY_SYNC_LIVE=true — the same
shadow-then-flip pattern as capital_policy.allocate_with_shadow.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Mapping, Sequence

_log = logging.getLogger(__name__)

_REPRICE_THRESHOLD_PCT = float(os.getenv("INVENTORY_REPRICE_THRESHOLD_PCT", "5.0"))


def _live() -> bool:
    return os.getenv("INVENTORY_SYNC_LIVE", "false").lower() == "true"


def _get_landed_cost(quote: Any) -> float:
    """Extract landed cost from SupplierQuote, SupplierOffer, or mapping."""
    if hasattr(quote, "landed_cost"):
        return float(quote.landed_cost)
    if hasattr(quote, "unit_cost") and hasattr(quote, "shipping_cost"):
        return round(float(quote.unit_cost) + float(quote.shipping_cost), 2)
    if hasattr(quote, "cost") and hasattr(quote, "shipping"):
        return round(float(quote.cost) + float(quote.shipping), 2)
    if isinstance(quote, dict):
        if "landed_cost" in quote:
            return float(quote["landed_cost"])
        unit = float(quote.get("unit_cost", quote.get("cost", 0.0)) or 0.0)
        shipping = float(quote.get("shipping_cost", quote.get("shipping", 0.0)) or 0.0)
        return round(unit + shipping, 2)
    return 0.0


def _is_out_of_stock(quote: Any) -> tuple[bool, str]:
    """Check whether *quote* indicates a stockout.

    Returns (is_out_of_stock, reason).
    Preserves unknown-versus-zero: inventory_units=None is unknown (in stock),
    inventory_units <= 0 is an explicit zero / stockout.
    """
    if quote is None:
        return True, "no_supplier_quote"

    # Explicit stock_ok flag
    stock_ok = getattr(quote, "stock_ok", None)
    if stock_ok is False:
        return True, "supplier_out_of_stock"
    if isinstance(quote, dict) and quote.get("stock_ok") is False:
        return True, "supplier_out_of_stock"

    # Explicit in_stock flag
    in_stock = getattr(quote, "in_stock", None)
    if in_stock is False:
        return True, "supplier_out_of_stock"
    if isinstance(quote, dict) and quote.get("in_stock") is False:
        return True, "supplier_out_of_stock"

    # Preserving unknown-versus-zero: None is unknown (in stock), <= 0 is zero (out of stock)
    units = getattr(quote, "inventory_units", None)
    if units is None and isinstance(quote, dict):
        units = quote.get("inventory_units")
    if units is not None:
        try:
            int_units = int(units)
            if int_units <= 0:
                return True, "zero_inventory_units"
        except (ValueError, TypeError):
            pass

    return False, ""


def _is_stale_observation(quote: Any, *, max_age_hours: float = 48.0) -> bool:
    """Check if *quote* carries data quality metadata indicating stale data."""
    quality = getattr(quote, "quality", None)
    if quality is None and isinstance(quote, dict):
        quality = quote.get("quality")
    if quality is None:
        return False

    from evaluation.quality import quality_reasons
    if isinstance(quality, dict):
        from backend.commerce.contracts import _quality_from_dict
        quality = _quality_from_dict(quality)
    reasons = quality_reasons(quality, max_age_hours=max_age_hours)
    return "stale_data" in reasons


_MISSING = object()


def _quote_value(quote: Any, *names: str) -> Any:
    """Read a quote field without collapsing missing fields into zero values."""
    for name in names:
        if isinstance(quote, Mapping):
            if name in quote:
                return quote[name]
        elif hasattr(quote, name):
            return getattr(quote, name)
    return _MISSING


def _quote_identity(quote: Any) -> tuple[str, str]:
    supplier = _quote_value(quote, "supplier", "supplier_id")
    product_id = _quote_value(quote, "product_id", "supplier_product_id")
    return (
        "" if supplier is _MISSING or supplier is None else str(supplier),
        "" if product_id is _MISSING or product_id is None else str(product_id),
    )


def _inventory_signature(quote: Any) -> tuple[str, Any]:
    """Return a stable quantity state, retaining unknown versus explicit zero."""
    units = _quote_value(quote, "inventory_units")
    if units is _MISSING or units is None:
        return ("unknown", None)
    try:
        return ("quantity", int(units))
    except (TypeError, ValueError):
        return ("invalid", str(units))


def _numeric_field_signature(value: Any) -> tuple[str, Any]:
    if value is _MISSING or value is None:
        return ("missing", None)
    try:
        return ("number", round(float(value), 8))
    except (TypeError, ValueError):
        return ("invalid", str(value))


def _landed_cost_signature(quote: Any) -> tuple[str, Any]:
    """Keep missing cost evidence distinct from an explicit numeric zero."""
    landed = _quote_value(quote, "landed_cost")
    if landed is not _MISSING:
        return ("landed", _numeric_field_signature(landed))

    unit_cost = _quote_value(quote, "unit_cost", "cost")
    shipping = _quote_value(quote, "shipping_cost", "shipping")
    if unit_cost is _MISSING and shipping is _MISSING:
        return ("missing", None)
    return (
        "components",
        _numeric_field_signature(unit_cost),
        _numeric_field_signature(shipping),
    )


def _reconciliation_signature(quote: Any) -> tuple[Any, ...]:
    """Fields whose disagreement could change reconciliation or its safety."""
    stock_ok = _quote_value(quote, "stock_ok")
    in_stock = _quote_value(quote, "in_stock")
    currency = _quote_value(quote, "currency")
    return (
        _quote_identity(quote),
        _inventory_signature(quote),
        ("missing" if stock_ok is _MISSING else stock_ok),
        ("missing" if in_stock is _MISSING else in_stock),
        _landed_cost_signature(quote),
        ("missing" if currency is _MISSING else currency),
    )


def _stable_observation_key(quote: Any) -> tuple[str, ...]:
    """Sort equivalent observations without depending on input order."""
    quality = _quote_value(quote, "quality")
    quality_values = tuple(
        str(_quote_value(quality, field))
        if _quote_value(quality, field) is not _MISSING
        else ""
        for field in ("provenance", "attribution", "completeness", "source_ref", "observed_at")
    )
    return (
        *_quote_identity(quote),
        repr(_reconciliation_signature(quote)),
        *quality_values,
    )


def _select_consistent_observation(quotes: Sequence[Any]) -> Any | None:
    """Select a deterministic quote or fail closed on fresh disagreement.

    Stale observations are retained only when no fresh observation exists so
    callers can preserve the existing skip-stale classification. If fresh
    observations disagree, an explicit out-of-stock observation is the only
    safe representative; otherwise no quote is returned.
    """
    if not quotes:
        return None

    fresh_quotes = [quote for quote in quotes if not _is_stale_observation(quote)]
    candidates = fresh_quotes or list(quotes)
    if not fresh_quotes:
        return sorted(candidates, key=_stable_observation_key)[0]

    signatures = {_reconciliation_signature(quote) for quote in candidates}
    if len(signatures) == 1:
        return sorted(candidates, key=_stable_observation_key)[0]

    # A disagreement containing an explicit stockout must not be resolved to
    # an optimistic in-stock observation. Preserve the zero/out-of-stock
    # classification and its provenance while failing closed on other conflicts.
    conservative = [quote for quote in candidates if _is_out_of_stock(quote)[0]]
    if conservative:
        return sorted(conservative, key=_stable_observation_key)[0]
    return None


def _extract_provenance(entry: Any, quote: Any | None) -> dict[str, Any]:
    """Extract supplier and quality provenance for auditability."""
    prov: dict[str, Any] = {
        "supplier": getattr(quote, "supplier", "") or getattr(quote, "supplier_id", "") if quote else entry.supplier,
        "supplier_product_id": getattr(quote, "product_id", "") or getattr(quote, "supplier_product_id", "") if quote else entry.supplier_product_id,
    }
    if quote is not None:
        quality = getattr(quote, "quality", None)
        if quality is None and isinstance(quote, dict):
            quality = quote.get("quality")
        if quality is not None:
            if hasattr(quality, "provenance"):
                prov["provenance"] = quality.provenance
                if getattr(quality, "source_ref", ""):
                    prov["source_ref"] = quality.source_ref
            elif isinstance(quality, dict):
                prov["provenance"] = quality.get("provenance", "unknown")
                if quality.get("source_ref"):
                    prov["source_ref"] = quality["source_ref"]
    return {k: v for k, v in prov.items() if v}


def _requote(
    entry: Any,
    offers: Sequence[Any] | Mapping[str, Any] | None = None,
) -> Any | None:
    """Find the current quote from *entry*'s bound supplier, if any.

    If *offers* is provided (e.g. offline supplier offers or observations),
    reconciles directly against them. Otherwise queries quote_all(entry.title).
    Prioritizes matching both supplier identity and supplier_product_id.
    """
    quotes: list[Any] = []
    if offers is not None:
        if isinstance(offers, Mapping):
            candidates: list[Any] = []
            for key in (entry.product_id, entry.supplier_product_id, entry.title):
                if key and key in offers:
                    val = offers[key]
                    if isinstance(val, (list, tuple)):
                        candidates.extend(val)
                    else:
                        candidates.append(val)
            if not candidates and "" in offers:
                candidates = list(offers.values())
            quotes = candidates
        elif isinstance(offers, (list, tuple)):
            quotes = [
                o for o in offers
                if getattr(o, "product_id", None) in (entry.product_id, entry.supplier_product_id)
                or getattr(o, "product_name", None) == entry.title
                or getattr(o, "title", None) == entry.title
                or (isinstance(o, dict) and o.get("product_id") in (entry.product_id, entry.supplier_product_id))
                or (isinstance(o, dict) and o.get("title") == entry.title)
            ]
    else:
        from backend.validation.suppliers import quote_all
        quotes = quote_all(entry.title)

    if not quotes:
        return None

    # Exact match on both supplier and supplier_product_id
    if entry.supplier and entry.supplier_product_id:
        exact_matches = [
            q for q in quotes
            if _quote_identity(q) == (entry.supplier, entry.supplier_product_id)
        ]
        if exact_matches:
            return _select_consistent_observation(exact_matches)

    # Match on supplier name
    if entry.supplier:
        matches = [
            q for q in quotes
            if _quote_identity(q)[0] == entry.supplier
        ]
        if matches:
            return _select_consistent_observation(matches)
        return None  # bound supplier no longer quoting -> treat as stockout

    return _select_consistent_observation(quotes)


def _reprice_action(entry: Any, quote: Any) -> dict[str, Any] | None:
    """Return a proposed reprice action if landed-cost drift exceeds the
    threshold, else None (no action needed)."""
    from backend.validation.margin_calculator import suggest_retail_price

    if entry.landed_cost <= 0:
        return None
    quote_landed_cost = _get_landed_cost(quote)
    if quote_landed_cost <= 0:
        return None
    drift_pct = abs(quote_landed_cost - entry.landed_cost) / entry.landed_cost * 100
    if drift_pct < _REPRICE_THRESHOLD_PCT:
        return None

    new_price = suggest_retail_price(quote_landed_cost, target_net_margin_pct=20.0)
    action: dict[str, Any] = {
        "action": "reprice",
        "product_id": entry.product_id,
        "old_price": entry.retail_price,
        "new_price": round(new_price, 2),
        "old_landed_cost": entry.landed_cost,
        "new_landed_cost": quote_landed_cost,
        "drift_pct": round(drift_pct, 2),
    }
    prov = _extract_provenance(entry, quote)
    if prov:
        action["provenance"] = prov
    return action


def reconcile_brand(
    brand: Any,
    offers: Sequence[Any] | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-quote every live catalog entry for *brand*; reprice/pause as needed.

    Accepts optional *offers* for deterministic offline batch reconciliation.
    Preserves unknown-versus-zero stock quantities, tracks supplier provenance,
    and handles duplicate/stale observations idempotently.

    Returns {status, checked, actions: [...], live}. All actions are always
    journaled as shadow_inventory_sync regardless of the live flag; only
    applied to the storefront when INVENTORY_SYNC_LIVE=true.
    """
    from backend.commerce.catalog import STATUS_LIVE, STATUS_PAUSED, product_catalog
    from backend.commerce.storefront import get_storefront

    live = _live()
    entries = product_catalog.for_brand(brand.brand_id, status=STATUS_LIVE)
    actions: list[dict] = []
    seen_products: set[str] = set()

    for entry in entries:
        if entry.product_id in seen_products:
            continue
        seen_products.add(entry.product_id)

        try:
            if offers is not None:
                quote = _requote(entry, offers=offers)
            else:
                quote = _requote(entry)
        except Exception as exc:
            _log.debug("inventory_requote_failed product=%s error=%s", entry.product_id, exc)
            quote = None

        if quote is not None and _is_stale_observation(quote):
            _log.warning("inventory_sync_stale_observation product=%s brand=%s", entry.product_id, brand.brand_id)
            actions.append({
                "action": "skip_stale",
                "product_id": entry.product_id,
                "reason": "stale_observation",
                "provenance": _extract_provenance(entry, quote),
            })
            continue

        is_stockout, stockout_reason = _is_out_of_stock(quote)
        if is_stockout:
            action: dict[str, Any] = {
                "action": "pause_stockout",
                "product_id": entry.product_id,
                "reason": stockout_reason,
            }
            prov = _extract_provenance(entry, quote)
            if prov:
                action["provenance"] = prov
            actions.append(action)
            continue

        reprice = _reprice_action(entry, quote)
        if reprice:
            actions.append(reprice)

    if live:
        storefront = get_storefront(brand)
        for action in actions:
            if action.get("action") == "skip_stale":
                action["applied"] = False
                continue
            # Each action applies independently so one storefront failure
            # doesn't abort the rest of the batch and lose track of which
            # actions actually landed — action["applied"] is the audit trail.
            try:
                if action["action"] == "pause_stockout":
                    storefront.update_product(brand, action["product_id"],
                                              status=STATUS_PAUSED, stock_ok=False)
                elif action["action"] == "reprice":
                    storefront.update_product(brand, action["product_id"],
                                              price=action["new_price"])
                action["applied"] = True
            except Exception as exc:
                action["applied"] = False
                action["apply_error"] = str(exc)
                _log.warning("inventory_sync_apply_failed brand=%s product=%s action=%s error=%s",
                            brand.brand_id, action["product_id"], action["action"], exc,
                            exc_info=True)

    _journal(brand.brand_id, actions, live)

    return {"status": "ok", "checked": len(entries), "actions": actions, "live": live}


def _journal(brand_id: str, actions: list[dict], live: bool) -> None:
    if not actions:
        return
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("inventory"), "shadow_inventory_sync",
            workflow="inventory_sync", step="reconcile",
            data={"brand_id": brand_id, "actions": actions, "live": live},
        )
    except Exception:
        _log.warning("inventory_sync_journal_failed brand=%s", brand_id, exc_info=True)


def reconcile_all_brands(
    offers_by_brand: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile every active brand's catalog. Returns a rollup summary."""
    from backend.commerce.brands import brand_registry

    total_checked = 0
    total_actions = 0
    per_brand = []
    for brand in brand_registry.all():
        if not brand.active:
            continue
        brand_offers = offers_by_brand.get(brand.brand_id) if offers_by_brand else None
        result = reconcile_brand(brand, offers=brand_offers)
        total_checked += result["checked"]
        total_actions += len(result["actions"])
        if result["actions"]:
            per_brand.append({"brand_id": brand.brand_id,
                              "actions": len(result["actions"])})

    return {"status": "ok" if total_checked else "skipped",
            "brands_checked": len([b for b in brand_registry.all() if b.active]),
            "products_checked": total_checked,
            "actions_taken": total_actions,
            "per_brand": per_brand}
