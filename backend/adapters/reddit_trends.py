"""backend.adapters.reddit_trends — Reddit product trend signals.

Scrapes top/hot posts from product-discovery subreddits using Reddit's
public JSON API (no auth required).  Returns signals compatible with
SignalEngine's format.

Subreddits monitored:
  - r/shutupandtakemymoney  — impulse/viral product discoveries
  - r/TikTokshop            — TikTok-native product trends
  - r/deals                 — price-sensitive high-demand products
  - r/BuyItForLife          — durable/evergreen products

Score computation:
  normalized_score = log(upvotes + 1) / log(MAX_UPVOTES)
  velocity = comment_count / max(age_hours, 1)   (activity rate)
"""
from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

_SUBREDDITS = [
    "shutupandtakemymoney",
    "TikTokshop",
    "deals",
    "BuyItForLife",
]

_CACHE_TTL_S = 1800   # 30 minutes — Reddit trends shift every 30-60 min
_MAX_POSTS   = 10     # top N posts per subreddit
_USER_AGENT  = "MarketOS/1.0 signal-bot (contact: ops@marketos.dev)"

# log-scale normaliser cap (posts with ~10k upvotes score ≈ 1.0)
import math
_LOG_CAP = math.log(10_000 + 1)

_cache: dict[str, Any] = {}
_cache_ts: float = 0.0


def _fetch_subreddit(subreddit: str, sort: str = "hot") -> list[dict]:
    """Fetch top posts from one subreddit via the public JSON API."""
    import urllib.request
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit={_MAX_POSTS}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=8) as resp:
        import json
        data = json.loads(resp.read().decode())
    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        title    = p.get("title", "").strip()
        ups      = int(p.get("ups", 0) or 0)
        comments = int(p.get("num_comments", 0) or 0)
        age_h    = max(1, (time.time() - float(p.get("created_utc", time.time()))) / 3600)
        flair    = (p.get("link_flair_text") or "").lower()
        if not title or ups < 10:
            continue
        posts.append({
            "title":    title,
            "ups":      ups,
            "comments": comments,
            "age_h":    age_h,
            "flair":    flair,
            "subreddit": subreddit,
            "url":      p.get("url", ""),
        })
    return posts


def _post_to_signal(post: dict) -> dict:
    """Convert a Reddit post to a SignalEngine-compatible signal dict."""
    # Extract product keyword from title (first 4 words, cleaned)
    title = post["title"]
    # Strip common noise words
    for noise in ("[Deal]", "[OC]", "PSA:", "PSA -", "[AMA]"):
        title = title.replace(noise, "").strip()
    words  = title.split()
    product = " ".join(words[:4]).strip("!?.,;:")

    ups      = post["ups"]
    comments = post["comments"]
    age_h    = post["age_h"]

    # Score: log-normalised upvotes (0–1)
    score    = min(1.0, math.log(ups + 1) / _LOG_CAP)

    # Velocity: comment activity per hour (proxy for trend momentum)
    velocity = min(1.0, (comments / max(age_h, 1)) / 20.0)

    return {
        "product":  product,
        "score":    round(score, 4),
        "velocity": round(velocity, 4),
        "source":   "reddit",
        "platform": "tiktok",        # TikTok-first strategy
        "subreddit": post["subreddit"],
        "raw_title": post["title"],
    }


def fetch_reddit_signals() -> list[dict]:
    """Fetch and cache product signals from monitored subreddits.

    Returns a list of signal dicts ready for SignalEngine.
    Falls back to empty list on any network error (never crashes the engine).
    """
    global _cache, _cache_ts
    now = time.time()
    if now - _cache_ts < _CACHE_TTL_S and _cache.get("signals"):
        return list(_cache["signals"])

    signals: list[dict] = []
    for sub in _SUBREDDITS:
        try:
            posts = _fetch_subreddit(sub, sort="hot")
            for post in posts:
                signals.append(_post_to_signal(post))
            _log.info("reddit_adapter_ok subreddit=%s posts=%d", sub, len(posts))
        except Exception as exc:
            _log.warning("reddit_adapter_failed subreddit=%s error=%s", sub, exc)

    if signals:
        _cache = {"signals": signals}
        _cache_ts = now
        _log.info("reddit_signals_fetched count=%d", len(signals))
    return signals


def register(engine: Any) -> None:
    """Register this adapter with a SignalEngine instance."""
    engine.register_source("reddit", fetch_reddit_signals)
    try:
        from backend.discovery.registry import discovery_registry
        discovery_registry.register("reddit", credential_env_vars=[], requires_auth=False)
    except Exception:
        pass
    _log.info("reddit_adapter_registered subreddits=%s", _SUBREDDITS)
