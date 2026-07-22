"""backend.organic.poster — organic content selection + publishing.

Candidates = live catalog products (brand-routed) plus playbook products
with a content gap (no scheduled post within the calendar's threshold).
Each post carries the product's landing URL with organic UTM tags so any
resulting orders attribute back to the exact post (closing the loop into
the Phase C order/attribution path).

Publishing goes through backend.integrations.postiz_client — dry-run by
default (ORGANIC_DRY_RUN=true), so this whole worker is rehearsable with
zero credentials. Post ↔ (product, brand) bindings persist to
state/organic_posts.json for the engagement ingester.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_POSTS_FILE = "organic_posts.json"
_MAX_POSTS_PER_RUN = int(os.getenv("ORGANIC_MAX_POSTS_PER_RUN", "3"))
_DEFAULT_PLATFORMS = ["tiktok", "instagram"]


def _load_post_index() -> dict:
    return load_json(state_path(_POSTS_FILE), default={"posts": []}) or {"posts": []}


def _save_post_index(index: dict) -> None:
    save_json_atomic(state_path(_POSTS_FILE), index)


def _already_posted_products(index: dict, within_hours: float = 72.0) -> set[str]:
    cutoff = datetime.now(timezone.utc).timestamp() - within_hours * 3600
    return {
        p["product"] for p in index.get("posts", [])
        if p.get("ts", 0) >= cutoff
    }


def _candidate_products() -> list[dict[str, Any]]:
    """Products worth posting about: live catalog entries first, then
    playbook products with a content gap."""
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    try:
        from backend.commerce.catalog import STATUS_LIVE, product_catalog
        from backend.commerce.brands import brand_registry
        for entry in product_catalog.all():
            if entry.status != STATUS_LIVE or not entry.stock_ok:
                continue
            brand = brand_registry.get(entry.brand_id)
            platforms = (list(brand.channel_preferences.keys())
                         if brand and brand.channel_preferences else _DEFAULT_PLATFORMS)
            candidates.append({
                "product": entry.title,
                "product_id": entry.product_id,
                "brand_id": entry.brand_id,
                "landing_url": entry.page_url,
                "platforms": platforms,
            })
            seen.add(entry.title)
    except Exception:
        _log.debug("catalog_candidates_unavailable", exc_info=True)

    try:
        from core.content.playbook import playbook_memory
        from core.ugc.content_calendar import content_calendar
        for pb in playbook_memory.all():
            if pb.product in seen:
                continue
            has_gap, _ = content_calendar.has_content_gap(pb.product)
            if has_gap:
                candidates.append({
                    "product": pb.product,
                    "product_id": "",
                    "brand_id": "",
                    "landing_url": "",
                    "platforms": _DEFAULT_PLATFORMS,
                })
                seen.add(pb.product)
    except Exception:
        _log.debug("playbook_candidates_unavailable", exc_info=True)

    return candidates


def _compose_post_text(product: str, landing_url: str, brand_id: str) -> str:
    from core.creative.generator import generate_creative

    script = generate_creative(product, "curiosity")
    text = script if isinstance(script, str) else str(script)
    text = text.strip()[:500]
    if landing_url:
        utm = f"utm_source=organic&utm_medium=social&utm_campaign={brand_id or 'organic'}"
        sep = "&" if "?" in landing_url else "?"
        text = f"{text}\n{landing_url}{sep}{utm}"
    return text


def run_organic_posting() -> dict[str, Any]:
    """Post organic content for up to N candidates. Returns a summary dict."""
    from backend.integrations.postiz_client import create_post

    index = _load_post_index()
    recently_posted = _already_posted_products(index)

    posted = 0
    results = []
    for cand in _candidate_products():
        if posted >= _MAX_POSTS_PER_RUN:
            break
        if cand["product"] in recently_posted:
            continue

        text = _compose_post_text(cand["product"], cand["landing_url"], cand["brand_id"])
        result = create_post(text, platforms=cand["platforms"])
        if result.get("status") != "ok" or not result.get("post_id"):
            _log.warning("organic_post_failed product=%s", cand["product"])
            continue

        record = {
            "post_id": result["post_id"],
            "product": cand["product"],
            "product_id": cand["product_id"],
            "brand_id": cand["brand_id"],
            "platforms": cand["platforms"],
            "dry_run": result.get("dry_run", True),
            "ts": datetime.now(timezone.utc).timestamp(),
        }
        index.setdefault("posts", []).append(record)
        posted += 1
        results.append(record)

        # Content-calendar bookkeeping (creator "system" = automated posting)
        try:
            from core.ugc.content_calendar import content_calendar
            content_calendar.schedule_post("system", cand["product"], content_type="post")
            content_calendar.mark_posted("system", cand["product"])
        except Exception:
            _log.debug("calendar_bookkeeping_failed", exc_info=True)

        try:
            from backend.orchestration.event_store import event_store, new_workflow_id
            event_store.append(
                new_workflow_id("organic"), "organic_post_created",
                workflow="organic", step="post",
                data={k: record[k] for k in
                      ("post_id", "product", "brand_id", "platforms", "dry_run")},
            )
        except Exception:
            pass

    if posted:
        _save_post_index(index)

    return {"status": "ok" if posted else "skipped",
            "posted": posted, "posts": results}
