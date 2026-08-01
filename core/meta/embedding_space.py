"""core.meta.embedding_space — unified feature embedding across domains."""
from __future__ import annotations

from typing import Any


_NUMERIC_KEYS = ("roas", "ctr", "cpa", "profit", "drawdown", "budget", "cac")


def embed_state(state: dict[str, Any], domain: str = "default") -> list[float]:
    """Convert an arbitrary state dict to a fixed-length numeric vector.

    Parameters
    ----------
    state:
        Campaign / system state dict.
    domain:
        Domain label.  Currently unused — reserved for future domain-conditioning
        (e.g. weighting features differently per platform such as TikTok vs Meta).

    Returns
    -------
    list[float]
        Fixed-length embedding of length ``len(_NUMERIC_KEYS)``.
    """
    return [float(state.get(k, 0.0)) for k in _NUMERIC_KEYS]
