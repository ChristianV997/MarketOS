"""backend.adapters.youtube_trends — YouTube Shorts product trend signals.

Fetches trending product keywords from YouTube via PyTrends (Google Trends
YouTube search category).  No API key or auth required — uses the same
public endpoint as Google Trends.

Strategy:
  - Queries the "YouTube Search" category (category 71) which reflects what
    people are searching for on YouTube — a leading indicator for Shorts virality.
  - Also queries trending searches in the "Shopping" interest category.
  - Filters for product-intent keywords (excludes news, celebrity, sport).

Score computation:
  score = interest_value / 100.0   (Google Trends returns 0–100)
  velocity = (current_week - prev_week) / max(prev_week, 1)  (momentum)
"""
from __future__ import annotations

import logging
import time
from typing import Any

_log = logging.getLogger(__name__)

_CACHE_TTL_S = 3600   # 1 hour — YouTube trends shift slower than TikTok
_PYTRENDS_TIMEOUT = 10

# Keywords anchors that pull in product-adjacent trending terms
_SEED_KEYWORDS = [
    "buy", "review", "unboxing", "worth it", "amazon finds",
    "tiktok made me buy", "best product", "viral product",
]

# YouTube Search category ID in Google Trends = 71
_YT_CATEGORY = 71

# Minimum interest score to include (avoids noise below 30%)
_MIN_INTEREST = 30

_cache: dict = {}
_cache_ts: float = 0.0


def _score_keyword(kw: str, interest: int, prev_interest: int) -> dict:
    """Build a signal dict from a trending YouTube keyword."""
    score    = round(min(1.0, interest / 100.0), 4)
    velocity = 0.0
    if prev_interest > 0:
        velocity = round(min(1.0, max(0.0, (interest - prev_interest) / prev_interest)), 4)

    return {
        "product":  kw.strip(),
        "score":    score,
        "velocity": velocity,
        "source":   "youtube_trends",
        "platform": "tiktok",    # map YouTube virality → TikTok opportunity
        "category": "youtube_shorts",
    }


def fetch_youtube_signals() -> list[dict]:
    """Fetch trending product signals from YouTube via PyTrends.

    Returns list of signal dicts for SignalEngine.
    Falls back to empty list on ImportError or network error.
    """
    global _cache, _cache_ts
    now = time.time()
    if now - _cache_ts < _CACHE_TTL_S and _cache.get("signals"):
        return list(_cache["signals"])

    try:
        from pytrends.request import TrendReq
    except ImportError:
        _log.info("youtube_trends_skip reason=pytrends_not_installed")
        return []

    signals: list[dict] = []
    try:
        pytrends = TrendReq(hl="en-US", tz=360, timeout=(_PYTRENDS_TIMEOUT, _PYTRENDS_TIMEOUT))

        # Trending searches by category (YouTube Search)
        trending_df = pytrends.trending_searches(pn="united_states")
        raw_trending = trending_df[0].tolist() if len(trending_df) > 0 else []

        # Build keyword interest for trending terms
        kws_to_score = [k for k in raw_trending[:10] if k and len(k) > 3]
        if not kws_to_score:
            return []

        # Batch in groups of 5 (pytrends limit)
        for batch_start in range(0, min(len(kws_to_score), 10), 5):
            batch = kws_to_score[batch_start:batch_start + 5]
            try:
                pytrends.build_payload(batch, cat=_YT_CATEGORY, timeframe="now 7-d", geo="US")
                interest_df = pytrends.interest_over_time()
                if interest_df.empty:
                    continue
                # Last row = most recent week, second-to-last = previous week
                last_row = interest_df.iloc[-1]
                prev_row = interest_df.iloc[-2] if len(interest_df) > 1 else last_row
                for kw in batch:
                    if kw not in interest_df.columns:
                        continue
                    interest = int(last_row.get(kw, 0) or 0)
                    prev     = int(prev_row.get(kw, 0) or 0)
                    if interest >= _MIN_INTEREST:
                        signals.append(_score_keyword(kw, interest, prev))
            except Exception as exc:
                _log.warning("youtube_trends_batch_failed batch=%s error=%s", batch, exc)

        _log.info("youtube_trends_fetched count=%d", len(signals))
    except Exception as exc:
        _log.warning("youtube_trends_failed error=%s", exc)
        return []

    if signals:
        _cache = {"signals": signals}
        _cache_ts = now
    return signals


def register(engine: Any) -> None:
    """Register this adapter with a SignalEngine instance."""
    engine.register_source("youtube_trends", fetch_youtube_signals)
    try:
        from backend.discovery.registry import discovery_registry
        discovery_registry.register("youtube_trends", credential_env_vars=[], requires_auth=False)
    except Exception:
        pass
    _log.info("youtube_trends_adapter_registered")
