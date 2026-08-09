"""backend.organic.engagement — post-metrics ingestion into the feedback loop.

Fetches engagement metrics for every tracked organic post, computes
engagement_rate = (likes + comments + shares) / impressions, persists a
per-product rollup (state/organic_engagement.json — consumed by the
Phase F organic→paid gate), and pushes organic events through
core.content.feedback.batch_classify — finally populating the
event["engagement_rate"] field the classifier has always read but nothing
ever fed.

Organic events are tagged source="organic": the classifier's organic
branch scores them on engagement alone (a post with zero ROAS is not a
LOSER — absence of purchase signal is not negative evidence).

Tier 5 evaluation (Mixpost as a complementary analytics source): the
consolidation roadmap asked whether Mixpost's (inovector/mixpost) more
polished built-in analytics dashboard is worth wiring in here alongside
Postiz, purely as a read-only complement — not a publishing-surface
replacement, Postiz remains correct for that. Conclusion: not adopted, for
a reason more fundamental than "unverified endpoint shape" (the bar that
was fine for e.g. Tier 4's AutoDS supplier client). Mixpost's own docs
site describes the freely self-hostable "Lite" edition as MIT-licensed,
but "Advanced Analytics" is called out as a feature of the separate paid
Pro/Enterprise tier — and a third-party community project
(github.com/btafoya/mixpost-api) exists specifically to bolt a REST API
onto self-hosted Mixpost for n8n/external integrations, which is itself
evidence the free, self-hostable edition doesn't ship a first-party
analytics API the way Postiz does. Revisit if a confirmed, documented
analytics endpoint turns out to be reachable on the free Lite tier (not
just Pro) — until then, get_post_metrics() via backend.integrations.
postiz_client stays the only engagement-metrics source feeding this gate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.core.persistence import load_json, save_json_atomic, state_path

_log = logging.getLogger(__name__)

_POSTS_FILE = "organic_posts.json"
_ROLLUP_FILE = "organic_engagement.json"


def _load(name: str, default):
    return load_json(state_path(name), default=default) or default


def ingest_engagement() -> dict[str, Any]:
    """Fetch metrics for tracked posts, update rollups, feed the classifier."""
    from backend.integrations.postiz_client import get_post_metrics

    index = _load(_POSTS_FILE, {"posts": []})
    posts = index.get("posts", [])
    if not posts:
        return {"status": "skipped", "reason": "no_posts"}

    rollup = _load(_ROLLUP_FILE, {})
    organic_events: list[dict] = []
    measured = 0

    for post in posts:
        post_id = post.get("post_id", "")
        product = post.get("product", "")
        if not post_id or not product:
            continue

        metrics = get_post_metrics(post_id)
        impressions = int(metrics.get("impressions", 0) or 0)
        if impressions <= 0:
            continue
        engaged = (int(metrics.get("likes", 0)) + int(metrics.get("comments", 0))
                   + int(metrics.get("shares", 0)))
        engagement_rate = round(engaged / impressions, 4)
        measured += 1

        entry = rollup.setdefault(product, {
            "brand_id": post.get("brand_id", ""),
            "posts": 0, "impressions": 0,
            "engagement_rates": [], "post_ids": [],
        })
        if post_id not in entry["post_ids"]:
            entry["posts"] += 1
            entry["post_ids"].append(post_id)
            entry["impressions"] += impressions
            entry["engagement_rates"].append(engagement_rate)
        else:
            # Re-measure: refresh the latest rate for this post
            idx = entry["post_ids"].index(post_id)
            if idx < len(entry["engagement_rates"]):
                entry["engagement_rates"][idx] = engagement_rate
        entry["last_ts"] = datetime.now(timezone.utc).timestamp()

        organic_events.append({
            "product": product,
            "brand_id": post.get("brand_id", ""),
            "source": "organic",
            "engagement_rate": engagement_rate,
            "impressions": impressions,
            "hook": "",
            "angle": "",
            "roas": 0.0, "ctr": 0.0, "cvr": 0.0,
        })

    save_json_atomic(state_path(_ROLLUP_FILE), rollup)

    classified = []
    if organic_events:
        try:
            from core.content.feedback import batch_classify
            classified = batch_classify(organic_events)
        except Exception:
            _log.debug("organic_classify_failed", exc_info=True)

    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("organic"), "organic_engagement_ingested",
            workflow="organic", step="ingest",
            data={
                "posts_measured": measured,
                "products": sorted({e["product"] for e in organic_events}),
                "labels": {e.get("product", ""): e.get("label", "")
                           for e in classified},
            },
        )
    except Exception:
        pass

    return {"status": "ok" if measured else "skipped",
            "posts_measured": measured,
            "products_updated": len({e["product"] for e in organic_events})}


def product_engagement(product: str) -> dict[str, Any]:
    """Rollup for one product (Phase F gate reads this).

    Returns {posts, impressions, mean_engagement_rate, last_ts} — zeros when
    the product has no measured organic history.
    """
    rollup = _load(_ROLLUP_FILE, {})
    entry = rollup.get(product)
    if not entry:
        return {"posts": 0, "impressions": 0, "mean_engagement_rate": 0.0,
                "last_ts": None}
    rates = entry.get("engagement_rates", [])
    return {
        "posts": int(entry.get("posts", 0)),
        "impressions": int(entry.get("impressions", 0)),
        "mean_engagement_rate": round(sum(rates) / len(rates), 4) if rates else 0.0,
        "last_ts": entry.get("last_ts"),
    }


def all_engagement_rates() -> list[float]:
    """Every product's mean engagement rate (for percentile computation)."""
    rollup = _load(_ROLLUP_FILE, {})
    out = []
    for entry in rollup.values():
        rates = entry.get("engagement_rates", [])
        if rates:
            out.append(round(sum(rates) / len(rates), 4))
    return out
