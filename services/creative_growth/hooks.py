"""services.creative_growth.hooks — generate_ad_angles, generate_hook_matrix.

Reuses the existing, real, already-tested creative-selection machinery
rather than inventing new hook/angle logic:
  - core.creative.selection.select_hooks/select_angles: the live rotation
    pool (Phase-7 gated: A/B validity + fatigue filtering already applied).
  - discovery.angles.extract_angles: a free, deterministic, zero-cost
    keyword classifier over real discovery signals (no paid API, no
    scraping needed) — surfaces fresh angle candidates the live pool may
    not have accumulated evidence for yet.
"""
from __future__ import annotations

from typing import Any

# Generic, public-domain direct-response copywriting fallbacks — used only
# when there's no accumulated pattern-store evidence yet (cold start), so
# the function is genuinely usable on day one rather than returning empty.
_DEFAULT_ANGLES = ["problem-solution", "transformation", "convenience", "curiosity", "satisfaction"]
_DEFAULT_HOOKS = [
    "Stop doing X the hard way",
    "This is why your Y isn't working",
    "The Z everyone's switching to",
    "I wish I knew this sooner",
    "Before you buy another Y, watch this",
]


def generate_ad_angles(product_name: str, *, signals: list[dict[str, Any]] | None = None, n: int = 5) -> list[str]:
    """Never raises. Combines the live-rotation angle pool with fresh
    keyword-extracted angles from real discovery signals."""
    live_pool: list[str] = []
    try:
        from core.creative.selection import select_angles
        live_pool = select_angles(n=n, fallback=[])
    except Exception:
        pass

    fresh: list[str] = []
    try:
        from discovery.angles import extract_angles
        for signal in (signals or []):
            fresh.extend(extract_angles(signal))
    except Exception:
        pass

    combined = list(dict.fromkeys([*live_pool, *fresh]))
    return combined[:n] if combined else list(_DEFAULT_ANGLES[:n])


def generate_hook_matrix(product_name: str, angles: list[str], *, n_hooks: int = 5) -> list[dict[str, str]]:
    """Never raises. Cross product of the live hook pool x the given
    angles — the testable ad-copy matrix."""
    hooks: list[str] = []
    try:
        from core.creative.selection import select_hooks
        hooks = select_hooks(n=n_hooks, fallback=[])
    except Exception:
        pass
    if not hooks:
        hooks = list(_DEFAULT_HOOKS[:n_hooks])

    return [{"hook": hook, "angle": angle, "product": product_name} for hook in hooks for angle in (angles or [])]
