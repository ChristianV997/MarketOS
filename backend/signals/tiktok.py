"""tiktok — mock TikTok signal scraper."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

_TEXTS = [
    "This $12 product changed my morning routine forever",
    "POV: you found the best budget skincare that actually works",
    "Day in my life saving $500/month with these hacks",
    "This one tool doubled my productivity — not clickbait",
    "Honest review: worth every penny or total scam?",
    "How I make an extra $1,000/month from home",
    "The Amazon find everyone is buying right now",
    "Why I switched and never looked back (price breakdown)",
    "Duped this $200 product for $18 and it's identical",
    "GRWM using products under $25 that look expensive",
    "My secret to getting 10x results in half the time",
    "This free tool saves me 3 hours every single day",
    "The hack nobody talks about for saving money online",
    "I tested every budget option — here's the winner",
    "How this one purchase paid for itself in a week",
    "The real reason influencers push this product (it works)",
    "Trying viral TikTok products so you don't have to",
    "From broke to $5k/month — the tools I used",
    "This app is genuinely life-changing (and free)",
    "Every entrepreneur needs this — here's why",
    "Stop wasting money on this — buy this instead",
    "I compared 10 products so you don't have to",
    "The truth about this viral trend (buyer's guide)",
    "How to get premium results on a starter budget",
    "This is why your ads aren't converting (fix this)",
]

_CATEGORIES = [
    "finance", "beauty", "lifestyle", "productivity", "review",
    "finance", "ecommerce", "finance", "beauty", "beauty",
    "productivity", "productivity", "finance", "review", "finance",
    "marketing", "review", "finance", "productivity", "business",
    "finance", "review", "marketing", "beauty", "marketing",
]


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def ingest_tiktok(query: str = "trending products") -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 9, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_TEXTS):
        h = _det_hash(query, i)
        views        = (h % 900_000) + 100_000
        likes        = ((_det_hash(query, i + 100)) % 90_000) + 10_000
        comments     = ((_det_hash(query, i + 200)) % 5_000) + 500
        raw_eng      = (likes * 1.5 + comments * 3) / max(views, 1)
        noise_factor = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement   = min(1.0, round(raw_eng * noise_factor, 4))
        sig = BaseSignal(
            source="tiktok",
            raw_text=text,
            engagement=engagement,
            category=_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://www.tiktok.com/@creator{(h % 9999):04d}/video/{h % 10**12:012d}",
            external_id=f"tt_{h % 10**15:015d}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals
