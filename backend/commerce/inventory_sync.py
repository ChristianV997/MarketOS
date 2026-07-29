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
from typing import Any

_log = logging.getLogger(__name__)

_REPRICE_THRESHOLD_PCT = float(os.getenv("INVENTORY_REPRICE_THRESHOLD_PCT", "5.0"))


def _live() -> bool:
    return os.getenv("INVENTORY_SYNC_LIVE", "false").lower() == "true"


def _requote(entry: Any) -> Any | None:
    """Find the current quote from *entry*'s bound supplier, if any."""
    from backend.validation.suppliers import quote_all

    quotes = quote_all(entry.title)
    if not quotes:
        return None
    if entry.supplier:
        matches = [q for q in quotes if q.supplier == entry.supplier]
        if matches:
            return matches[0]
        return None  # bound supplier no longer quoting -> treat as stockout
    return quotes[0]


def _reprice_action(entry: Any, quote: Any) -> dict[str, Any] | None:
    """Return a proposed reprice action if landed-cost drift exceeds the
    threshold, else None (no action needed)."""
    from backend.validation.margin_calculator import suggest_retail_price

    if entry.landed_cost <= 0:
        return None
    drift_pct = abs(quote.landed_cost - entry.landed_cost) / entry.landed_cost * 100
    if drift_pct < _REPRICE_THRESHOLD_PCT:
        return None

    new_price = suggest_retail_price(quote.landed_cost, target_net_margin_pct=20.0)
    return {
        "action": "reprice",
        "product_id": entry.product_id,
        "old_price": entry.retail_price,
        "new_price": round(new_price, 2),
        "old_landed_cost": entry.landed_cost,
        "new_landed_cost": quote.landed_cost,
        "drift_pct": round(drift_pct, 2),
    }


def reconcile_brand(brand: Any) -> dict[str, Any]:
    """Re-quote every live catalog entry for *brand*; reprice/pause as needed.

    Returns {status, checked, actions: [...], live}. All actions are always
    journaled as shadow_inventory_sync regardless of the live flag; only
    applied to the storefront when INVENTORY_SYNC_LIVE=true.
    """
    from backend.commerce.catalog import STATUS_LIVE, STATUS_PAUSED, product_catalog
    from backend.commerce.storefront import get_storefront

    live = _live()
    entries = product_catalog.for_brand(brand.brand_id, status=STATUS_LIVE)
    actions: list[dict] = []

    for entry in entries:
        try:
            quote = _requote(entry)
        except Exception as exc:
            _log.debug("inventory_requote_failed product=%s error=%s", entry.product_id, exc)
            quote = None

        if quote is None:
            actions.append({
                "action": "pause_stockout",
                "product_id": entry.product_id,
                "reason": "no_supplier_quote",
            })
            continue

        reprice = _reprice_action(entry, quote)
        if reprice:
            actions.append(reprice)

    if live:
        storefront = get_storefront(brand)
        for action in actions:
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


def reconcile_all_brands() -> dict[str, Any]:
    """Reconcile every active brand's catalog. Returns a rollup summary."""
    from backend.commerce.brands import brand_registry

    total_checked = 0
    total_actions = 0
    per_brand = []
    for brand in brand_registry.all():
        if not brand.active:
            continue
        result = reconcile_brand(brand)
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
