"""meta — mock Meta/Facebook signal scraper."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

_TEXTS = [
    "Just hit $10k/month using this exact strategy — sharing it all",
    "Stop scrolling — this product literally changed my life",
    "The Facebook ads hack no one talks about (works in 2025)",
    "I quit my 9-5 after discovering this income stream",
    "This one product gets 5 stars every single time",
    "Moms are making $3k/month with this simple method",
    "The real reason your Facebook ads aren't converting",
    "Free webinar: how I built a $50k/month business from home",
    "This supplement changed my energy levels in 3 days",
    "The budget hack that helped me save $10k this year",
    "Everyone in our group is buying this — here's why",
    "Warning: don't buy this product before reading this",
    "The tool I use to automate my entire business",
    "How I generated 500 leads for under $100",
    "The truth about this trending wellness product",
    "This is hands-down the best value purchase of 2025",
    "How our community saved $50k collectively this month",
    "The influencer marketing strategy that actually works",
    "From side hustle to full-time income — my story",
    "The ad creative formula that generates 8x ROAS",
    "This free resource is worth thousands (grab it now)",
    "Why smart buyers always choose this over the alternative",
    "The scaling strategy that took us from 1k to 100k",
    "Real results: members share their wins this week",
    "The product everyone is gifting this season",
]

_CATEGORIES = [
    "finance", "lifestyle", "marketing", "finance", "review",
    "finance", "marketing", "finance", "lifestyle", "finance",
    "lifestyle", "review", "productivity", "marketing", "lifestyle",
    "review", "finance", "marketing", "finance", "marketing",
    "finance", "review", "business", "lifestyle", "ecommerce",
]


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def ingest_meta(query: str = "facebook trending") -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 11, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_TEXTS):
        h = _det_hash(query, i)
        reactions    = (h % 50_000) + 500
        shares       = ((_det_hash(query, i + 100)) % 10_000) + 100
        comments     = ((_det_hash(query, i + 200)) % 8_000) + 50
        reach        = ((_det_hash(query, i + 300)) % 500_000) + 10_000
        raw_eng      = (reactions * 1.0 + shares * 3.0 + comments * 2.0) / max(reach, 1)
        noise_factor = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement   = min(1.0, round(raw_eng * noise_factor, 4))
        post_id = f"{h % 10**15:015d}"
        sig = BaseSignal(
            source="meta",
            raw_text=text,
            engagement=engagement,
            category=_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://www.facebook.com/permalink.php?story_fbid={post_id}",
            external_id=f"fb_{post_id}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals
