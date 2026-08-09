"""core.content.select — select winning organic posts for ad promotion."""
from __future__ import annotations

from typing import Any

from core.content.scoring import score as _score

_PROMOTE_MIN_VIEWS = 50_000     # threshold: organic video must reach 50k views before paid promotion
_PROMOTE_MIN_ENGAGEMENT = 0.05  # threshold: 5% engagement rate indicates strong audience resonance


def select_winners(posts: list[dict[str, Any]], top_n: int = 2) -> list[dict[str, Any]]:
    """Return the top *top_n* highest-scoring posts.

    Parameters
    ----------
    posts:
        List of post dicts each containing a ``"score"`` key (or raw metrics
        to score on the fly).
    top_n:
        Number of winners to return (default 2).

    Returns
    -------
    list[dict]
        Top-scoring posts sorted by descending score.
    """
    scored = []
    for p in posts:
        s = p.get("score") if "score" in p else _score(p)
        scored.append({**p, "score": s})
    ranked = sorted(scored, key=lambda x: x["score"], reverse=True)
    return ranked[:top_n]


def promote_to_ads(post: dict[str, Any]) -> bool:
    """Return ``True`` when *post* meets the organic promotion threshold.

    Threshold (Step 68):
    - views > 50,000
    - engagement rate > 5 %

    Parameters
    ----------
    post:
        Post dict with ``views`` and ``engagement`` keys.

    Returns
    -------
    bool
        Whether the post qualifies for paid promotion.
    """
    views = int(post.get("views", 0))
    engagement = float(post.get("engagement", 0.0))
    return views > _PROMOTE_MIN_VIEWS and engagement > _PROMOTE_MIN_ENGAGEMENT
