"""backend.launch.channel_selector — pick the ad-spend split per brand.

Before this module, every launch — regardless of brand, category, or
observed channel preference — split budget by a single hardcoded 55/45
tiktok/meta constant (duplicated in backend.launch.orchestrator._SPLIT and
backend.orchestration.transaction._SPLIT). A brand's own
channel_preferences field (backend.commerce.brands.Brand) has existed
since Commerce Phase A but nothing ever read it for budget allocation —
only organic posting platform choice consumed it.

select_weights() replaces the hardcoded split: brand.channel_preferences
when set, else the legacy 55/45 default (byte-identical to today for any
brand that hasn't been given explicit preferences). Always journals both
splits as shadow_channel_selection; returns the selected split only when
CHANNEL_SELECT_LIVE=true, so nothing changes for existing brands until the
flag flips.

A category-prior fallback (channel affinity learned from category-level
data) is a natural extension point once backend.data.category_priors
exists — not built yet, so this module only consults brand preferences.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_LEGACY_SPLIT = {"tiktok": 0.55, "meta": 0.45}


def _live() -> bool:
    return os.getenv("CHANNEL_SELECT_LIVE", "false").lower() == "true"


def select_weights(platforms: tuple[str, ...], brand: Any = None) -> dict[str, float]:
    """Return {platform: weight} for *platforms*, always summing to 1.0.

    Priority: brand.channel_preferences (when it covers at least one of
    the requested platforms) -> the legacy 55/45 default.
    """
    legacy = {p: _LEGACY_SPLIT.get(p, 1.0 / len(platforms)) for p in platforms}
    legacy_total = sum(legacy.values()) or 1.0
    legacy = {p: w / legacy_total for p, w in legacy.items()}

    selected = None
    source = "legacy_default"
    prefs = getattr(brand, "channel_preferences", None) if brand is not None else None
    if prefs and any(p in prefs for p in platforms):
        selected = {p: float(prefs.get(p, 0.0)) for p in platforms}
        source = "brand_preference"

    if selected is None:
        selected = dict(legacy)

    total = sum(selected.values()) or 1.0
    selected = {p: selected[p] / total for p in platforms}

    _journal(platforms, legacy, selected, source, brand)
    return selected if _live() else legacy


def _journal(platforms, legacy, selected, source, brand) -> None:
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("channelselect"), "shadow_channel_selection",
            workflow="channel_selection", step="select",
            data={"platforms": list(platforms), "legacy_split": legacy,
                 "selected_split": selected, "source": source,
                 "brand_id": getattr(brand, "brand_id", ""), "live": _live()},
        )
    except Exception:
        _log.warning("channel_selection_journal_failed", exc_info=True)


__all__ = ["select_weights"]
