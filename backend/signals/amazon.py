"""amazon — mock Amazon product signal scraper."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

_TEXTS = [
    "Worth every penny — this tool saved me $200 in one month",
    "Best buy of 2025: this productivity tool has 47,000 5-star reviews",
    "The price is insane — this standing desk earns back productivity daily",
    "Save $150/month with this air purifier — best buy in the category",
    "This $18 resistance band set earns its worth vs a $200 gym membership",
    "Amazon's best-seller notebook — worth buying 10 at a time",
    "Growth hack: this posture corrector scales your work hours pain-free",
    "How to save $111 monthly — forget the $600 Vitamix buy this $89 blender",
    "The ergonomic tool worth every cent — eliminated my wrist pain",
    "Productivity growth: this under-desk bike earns its price tag in 2 weeks",
    "Save $80/month — reusable produce bags worth every penny",
    "This $29 tool makes videos look professional — price-to-value unmatched",
    "Scale your desk setup — the cable management tool everyone needs to buy",
    "Best meal prep tool for the price — worth every cent, 5 years running",
    "Productivity wins: blue light glasses worth buying at this price point",
    "Worth the hype — Instant Pot is the best buy for price-conscious cooks",
    "Save on therapy — this $15 book earns 4.8 stars and pays back 10x",
    "Earn better sleep: this cooling sleep mask worth the premium price",
    "Scale your energy: this wireless charger tool earns 3x faster results",
    "Productivity essential: foam roller worth buying — PTs earn from referrals",
]

_CATEGORIES = [
    "lifestyle", "productivity", "productivity", "lifestyle", "lifestyle",
    "productivity", "lifestyle", "review", "productivity", "lifestyle",
    "lifestyle", "productivity", "productivity", "lifestyle", "lifestyle",
    "lifestyle", "productivity", "lifestyle", "productivity", "lifestyle",
]


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def ingest_amazon(query: str = "amazon best sellers") -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_TEXTS):
        h = _det_hash(query, i)
        reviews      = (h % 48_000) + 1_000
        rating_tenth = ((_det_hash(query, i + 100)) % 10) + 40
        trend_boost  = ((_det_hash(query, i + 200)) % 20) / 100.0
        raw_eng      = (min(reviews, 50_000) / 50_000.0) * 0.5 \
                     + (rating_tenth / 50.0) * 0.4 \
                     + trend_boost * 0.1
        noise_factor = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement   = min(1.0, round(raw_eng * noise_factor, 4))
        asin = f"B{h % 10**9:09d}"
        sig = BaseSignal(
            source="amazon",
            raw_text=text,
            engagement=engagement,
            category=_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://www.amazon.com/dp/{asin}",
            external_id=f"amz_{asin}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals
