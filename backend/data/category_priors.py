"""backend.data.category_priors — category-level statistical priors,
offline-ingested from public e-commerce datasets, never fetched at runtime.

Before this module, every category-level constant in the codebase
(margin_calculator.CATEGORY_RETURN_RATES, ltv.CATEGORY_REPEAT_RATE_PRIOR,
the channel split in backend.launch.channel_selector) was a hand-picked
benchmark number. This module is the seam that lets those numbers instead
be derived from real e-commerce data — Amazon Reviews 2023 (per-category
rating distributions, a return-risk proxy) and Olist's 100k real Brazilian
orders (real repeat-purchase rates, real delivery-day distributions) —
without touching any consumer's code path.

load_priors() reads a state/ override (an operator can refresh priors
without a code change) falling back to the committed seed file
(backend/data/seed/category_priors.json). category_prior(category, field,
default) is the single lookup every consumer should use.

The seed file ships EMPTY: no category has any priors until an operator
actually downloads the real datasets and runs
scripts/ingest_category_priors.py against them. This module never
fabricates a number standing in for real data — an empty or missing prior
falls back to the caller's own existing default, so nothing changes until
real data is ingested. Every consumer is additionally gated behind
CATEGORY_PRIORS_LIVE (default false): category_prior() returns the
caller's default unconditionally while the flag is off, so wiring this in
is a pure no-op until both (a) real priors exist and (b) the flag is
flipped.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from backend.core.persistence import load_json, state_path

_log = logging.getLogger(__name__)

_SEED_PATH = os.path.join(os.path.dirname(__file__), "seed", "category_priors.json")
_STATE_OVERRIDE_FILE = "category_priors.json"


def priors_live() -> bool:
    return os.getenv("CATEGORY_PRIORS_LIVE", "false").lower() == "true"


def load_priors() -> dict[str, dict[str, Any]]:
    """{category: {field: value, ...}, ...} — a state/ override takes
    precedence over the committed seed; a missing/unreadable/empty file at
    either location degrades to {} rather than raising."""
    override = load_json(state_path(_STATE_OVERRIDE_FILE), default=None)
    if override:
        return override
    return load_json(_SEED_PATH, default={}) or {}


def category_prior(category: str, field: str, default: Any = None) -> Any:
    """Look up one *field* for *category* (e.g. field="repeat_rate",
    field="return_proxy", field="channel_affinity").

    Returns *default* unconditionally while CATEGORY_PRIORS_LIVE is false
    (the default) — every consumer's behavior is provably unchanged until
    this is deliberately turned on for a category that actually has ingested
    data. Never raises.
    """
    if not priors_live():
        return default
    try:
        value = load_priors().get(category, {}).get(field)
        return value if value is not None else default
    except Exception as exc:
        _log.debug("category_prior_lookup_failed category=%s field=%s error=%s",
                  category, field, exc)
        return default


__all__ = ["load_priors", "category_prior", "priors_live"]
