"""google_trends — Google Trends signal scraper (real pytrends, mock fallback)."""
from __future__ import annotations
import hashlib
import logging
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

logger = logging.getLogger(__name__)

_MOCK_TEXTS = [
    "best AI productivity tools to scale your business 2025",
    "how to make money with automation and ChatGPT",
    "passive income growth strategies that actually earn",
    "best budgeting tool to save money for millennials",
    "how to scale a dropshipping business in 2025",
    "side hustle growth hacks for extra income",
    "best credit card tool for rewards — worth the price",
    "how to earn from real estate with no money hack",
    "print on demand — worth it to scale your income",
    "best productivity system and automation tools for entrepreneurs",
    "how to get free stuff and save money on Amazon",
    "viral marketing growth strategies that earn results",
    "best online courses worth buying to make money",
    "how to scale a business on social media with automation",
    "best affiliate programs worth the price — high ticket earn",
    "how to automate your business and scale growth in 2025",
    "remote work productivity tools everyone needs to buy",
    "best way to save money and growth-hack subscriptions",
    "how to sell on Amazon FBA profitably — earn at scale",
    "trending products worth selling online for growth 2025",
]

_MOCK_CATEGORIES = [
    "productivity", "finance", "finance", "finance", "ecommerce",
    "finance", "finance", "finance", "ecommerce", "productivity",
    "ecommerce", "marketing", "finance", "marketing", "marketing",
    "productivity", "productivity", "finance", "ecommerce", "ecommerce",
]

_CATEGORY_MAP = {
    "productivity": "productivity",
    "finance":      "finance",
    "ecommerce":    "ecommerce",
    "marketing":    "marketing",
    "business":     "business",
}


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def _mock_signals(query: str) -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 7, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_MOCK_TEXTS):
        h = _det_hash(query, i)
        search_volume = (h % 90) + 10
        rising_pct    = ((_det_hash(query, i + 100)) % 500) + 50
        norm_volume   = search_volume / 100.0
        norm_rising   = min(1.0, rising_pct / 500.0)
        raw_eng       = norm_volume * 0.6 + norm_rising * 0.4
        noise_factor  = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement    = min(1.0, round(raw_eng * noise_factor, 4))
        sig = BaseSignal(
            source="google_trends",
            raw_text=text,
            engagement=engagement,
            category=_MOCK_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://trends.google.com/trends/explore?q={text.replace(' ', '%20')}",
            external_id=f"gt_{h % 10**12:012d}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals


def _live_signals(query: str) -> list[BaseSignal]:
    from pytrends.request import TrendReq  # lazy import; only used on live path

    pytrends = TrendReq(hl="en-US", tz=0, timeout=(10, 25))
    kw_list = [query] if query else ["trending"]
    pytrends.build_payload(kw_list, cat=0, timeframe="now 7-d", geo="US")
    related = pytrends.related_queries()

    rows: list[tuple[str, int]] = []
    for kw in kw_list:
        kw_data = related.get(kw, {})
        for kind in ("rising", "top"):
            df = kw_data.get(kind)
            if df is not None and not df.empty:
                for _, row in df.head(10).iterrows():
                    rows.append((str(row["query"]), int(row["value"])))

    if not rows:
        return []

    # Normalise values to [0, 1] engagement proxy
    max_val = max(v for _, v in rows) or 1
    ts = datetime.now(tz=timezone.utc).isoformat()
    signals: list[BaseSignal] = []
    for i, (text, value) in enumerate(rows[:20]):
        h = _det_hash(query, i)
        engagement = round(min(1.0, value / max_val), 4)
        category = "marketing"  # pytrends doesn't provide category; default to marketing
        sig = BaseSignal(
            source="google_trends",
            raw_text=text,
            engagement=engagement,
            category=category,
            timestamp=ts,
            url=f"https://trends.google.com/trends/explore?q={text.replace(' ', '%20')}",
            external_id=f"gt_{h % 10**12:012d}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals


def ingest_google_trends(query: str = "google trends rising") -> list[BaseSignal]:
    try:
        signals = _live_signals(query)
        if signals:
            logger.info("google_trends: live pytrends returned %d signals", len(signals))
            return signals
        logger.warning("google_trends: live returned 0 signals, falling back to mock")
    except Exception as exc:  # network errors, rate limits, etc.
        logger.warning("google_trends: live call failed (%s), falling back to mock", exc)
    return _mock_signals(query)
