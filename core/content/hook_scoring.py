"""core.content.hook_scoring — score individual hooks from performance data."""
from __future__ import annotations

from typing import Any

from core.content.scoring import _post_score


def score(post: dict[str, Any]) -> float:
    """Compute a hook-level performance score.

    Delegates to the shared scoring kernel in :mod:`core.content.scoring`.

    Parameters
    ----------
    post:
        Post feature dict with ``engagement`` and ``views`` keys.

    Returns
    -------
    float
    """
    return _post_score(post)
