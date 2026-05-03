"""youtube — mock YouTube signal scraper."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

_TEXTS = [
    "I tried every side hustle for 30 days — results",
    "The TRUTH about passive income (what nobody tells you)",
    "Best budget products that outperform luxury brands",
    "How I automated my business and 10x'd revenue",
    "Top 10 productivity tools you need in 2025",
    "Honest dropshipping results after 90 days",
    "The only budgeting system that actually works",
    "I spent $1,000 testing viral products — winner inside",
    "How to start earning online with $0 investment",
    "The best investing strategy for beginners in 2025",
    "Why everyone is switching to this productivity app",
    "How I save $2,000/month on a regular salary",
    "The side hustle making me $500/week passively",
    "This marketing strategy got me 10,000 customers",
    "Amazon FBA vs Shopify — full honest breakdown",
    "How to make money online (no experience required)",
    "The stock market hack that changed my portfolio",
    "Everything wrong with traditional budgeting (and fix)",
    "Review: is this $49 course actually worth it?",
    "The tool every freelancer needs (and it's free)",
    "How to earn $100/day from YouTube without a camera",
    "Why the rich buy assets not liabilities — explained",
    "The secret to making viral content that sells",
    "Scaling my Etsy shop from $0 to $10k/month",
    "Complete guide to affiliate marketing in 2025",
]

_CATEGORIES = [
    "finance", "finance", "review", "business", "productivity",
    "ecommerce", "finance", "review", "finance", "finance",
    "productivity", "finance", "finance", "marketing", "ecommerce",
    "finance", "finance", "finance", "review", "productivity",
    "finance", "finance", "marketing", "ecommerce", "marketing",
]


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def ingest_youtube(query: str = "make money online") -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_TEXTS):
        h = _det_hash(query, i)
        views         = (h % 2_000_000) + 50_000
        likes         = ((_det_hash(query, i + 100)) % 80_000) + 2_000
        comments      = ((_det_hash(query, i + 200)) % 8_000) + 200
        likes_norm    = min(1.0, likes    / 80_000.0)
        comments_norm = min(1.0, comments / 8_000.0)
        views_factor  = 1.0 - min(1.0, views / 2_000_000.0)
        raw_eng       = likes_norm * 0.50 + comments_norm * 0.30 + views_factor * 0.20
        noise_factor  = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement    = min(1.0, round(raw_eng * noise_factor, 4))
        vid_id = f"{h % 10**11:011d}"
        sig = BaseSignal(
            source="youtube",
            raw_text=text,
            engagement=engagement,
            category=_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://www.youtube.com/watch?v={vid_id}",
            external_id=f"yt_{vid_id}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals
