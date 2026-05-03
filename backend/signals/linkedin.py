"""linkedin — mock LinkedIn signal scraper."""
from __future__ import annotations
import hashlib
from datetime import datetime, timezone
from .base import BaseSignal, validate_signal

_TEXTS = [
    "We scaled growth from $0 to $1M ARR using automation — full playbook",
    "The cold email tool that earns 40% reply rates — worth the price",
    "Automation is the secret productivity hack of the year — scale faster",
    "How we cut CAC 60% — the growth hack that earned us 10x returns",
    "The hiring tool every founder needs — worth the price to scale faster",
    "LinkedIn ads are the best buy right now — earn 5x ROAS at this price",
    "Our B2B productivity tool earns 11% conversion — full scale breakdown",
    "The SaaS pricing hack that earns and scales revenue 3x",
    "Why founders waste budget — the secret to growth channel automation",
    "The only sales tool worth buying in 2025 — copy this script to earn",
    "We fired our agency to save money and scale in-house — best buy decision",
    "How to scale a personal brand that earns leads on automation",
    "The content tool and growth strategy that earned us 50k followers",
    "Secret to scaling a remote team — worth every productivity investment",
    "Our retention tool earned 95% growth — the secret product change",
    "B2B founders: the distribution hack worth your time to scale",
    "The outbound automation tool that earns 30 sales calls per month",
    "How I scaled consulting revenue 4x — the earn-more-save-time hack",
    "The partnership tool that eliminates cold outreach — worth the price",
    "Why product-led growth and automation wins in every category",
]

_CATEGORIES = [
    "business", "marketing", "productivity", "marketing", "business",
    "marketing", "marketing", "business", "business", "marketing",
    "business", "marketing", "marketing", "business", "business",
    "marketing", "marketing", "finance", "business", "business",
]


def _det_hash(query: str, i: int) -> int:
    return int(hashlib.md5(f"{query}:{i}".encode()).hexdigest(), 16)


def ingest_linkedin(query: str = "linkedin trending business") -> list[BaseSignal]:
    signals: list[BaseSignal] = []
    base_ts = datetime(2025, 5, 1, 13, 0, 0, tzinfo=timezone.utc)
    for i, text in enumerate(_TEXTS):
        h = _det_hash(query, i)
        reactions    = (h % 12_000) + 200
        comments     = ((_det_hash(query, i + 100)) % 800) + 20
        shares       = ((_det_hash(query, i + 200)) % 600) + 10
        norm_r       = reactions / 12_200.0
        norm_c       = comments  / 820.0
        norm_s       = shares    / 610.0
        raw_eng      = norm_r * 0.50 + norm_c * 0.30 + norm_s * 0.20
        noise_factor = 0.50 + (_det_hash(query, i + 500) % 51) / 100.0
        engagement   = min(1.0, round(raw_eng * noise_factor, 4))
        post_id      = f"{h % 10**18:018d}"
        sig = BaseSignal(
            source="linkedin",
            raw_text=text,
            engagement=engagement,
            category=_CATEGORIES[i],
            timestamp=base_ts.isoformat(),
            url=f"https://www.linkedin.com/feed/update/urn:li:activity:{post_id}/",
            external_id=f"li_{post_id}",
        )
        if not validate_signal(sig):
            continue
        signals.append(sig)
    return signals
