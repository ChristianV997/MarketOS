"""google — mock Google Ads/Search signal scraper."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

_TEXTS = [
    "best productivity app 2025 review",
    "how to make money online fast legitimate",
    "buy cheap vs expensive — which is worth it",
    "top rated weight loss supplement that works",
    "best budget laptop for working from home",
    "earn passive income while you sleep strategies",
    "how to save money on groceries every month",
    "best investment for beginners low risk 2025",
    "work from home jobs that pay well no experience",
    "best ecommerce platform to start selling online",
    "how to grow Instagram followers organically fast",
    "best email marketing tool for small business",
    "how to start dropshipping step by step guide",
    "best CRM software for small business affordable",
    "top rated skincare routine for beginners budget",
    "how to start affiliate marketing with no money",
    "best project management tool for remote teams",
    "how to automate social media posting free",
    "best online course platform to sell courses",
    "how to get more clients as a freelancer fast",
    "earn money from home without investment legit",
    "best financial planning app for millennials",
    "how to scale a business without hiring",
    "best AI tools for entrepreneurs in 2025",
    "top conversion rate optimization strategies",
]

_CATEGORIES = [
    "productivity", "finance", "review", "lifestyle", "review",
    "finance", "finance", "finance", "finance", "ecommerce",
    "marketing", "marketing", "ecommerce", "productivity", "beauty",
    "marketing", "productivity", "marketing", "ecommerce", "finance",
    "finance", "finance", "business", "productivity", "marketing",
]


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def ingest_google(query: str = "google search trends") -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_TEXTS):
        h = _det_hash(query, i)
        cpc_cents    = ((_det_hash(query, i + 100)) % 800) + 50
        ctr_pct      = ((_det_hash(query, i + 200)) % 15) + 1
        ctr_norm     = (ctr_pct - 1) / 14.0
        cpc_norm     = min(cpc_cents, 800) / 800.0
        raw_eng      = ctr_norm * 0.65 + cpc_norm * 0.35
        noise_factor = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement   = min(1.0, round(raw_eng * noise_factor, 4))
        sig = BaseSignal(
            source="google",
            raw_text=text,
            engagement=engagement,
            category=_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://www.google.com/search?q={text.replace(' ', '+')}",
            external_id=f"goog_{h % 10**12:012d}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals
