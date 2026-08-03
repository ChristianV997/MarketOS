"""core.creative.selection — Phase 7 creative pool selection.

Single source of truth for choosing which hooks/angles enter the live
rotation, gated by two independently-flippable flags (matching the rolling
hour-by-hour rollout in docs/archive/DEPLOYMENT_GUIDE.md):

  PHASE7_AB_TEST_VALIDITY_LIVE      restrict the candidate pool to hooks/
                                    angles that have reached statistical
                                    validity (n >= 20 observations) instead
                                    of PatternStore's raw top-N.
  PHASE7_FATIGUE_DETECTION_LIVE     filter out hooks/angles whose rolling
                                    recent ROAS has declined vs historical
                                    (HookFatigueDetector / SequenceOptimizer).

Both legacy and Phase-7 selections are always computed and journaled to the
event store as a shadow_<kind>_selection event; the legacy pool is returned
unless the relevant flag is live, so no live rotation changes before its
shadow log clears validation.
"""
from __future__ import annotations

import os


def _flag(name: str) -> bool:
    return os.getenv(name, "false").lower() == "true"


def _journal_selection(kind: str, legacy: list[str], final: list[str],
                        fatigue_live: bool, validity_live: bool, degraded: bool) -> None:
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("creative_select"), f"shadow_{kind}_selection",
            workflow="creative_selection", step=kind,
            data={
                "legacy": legacy,
                "phase7": final,
                "fatigue_detection_live": fatigue_live,
                "ab_test_validity_live": validity_live,
                "degraded_all_fatigued": degraded,
            },
        )
    except Exception:
        pass  # journaling must never break creative selection


def _select_with_fatigue_ladder(
    base: list[str], legacy: list[str], fallback: list[str], fatigued: set[str],
) -> tuple[list[str], bool]:
    """Filter fatigued candidates out of `base`, broadening to `legacy` then
    `fallback` if that empties the pool entirely. Only as an absolute last
    resort (every known candidate is fatigued) does it return `base`
    unfiltered — never an empty pool, and never a silent, unflagged
    reversal of the fatigue filter.

    Returns (final_pool, degraded) where degraded=True means fatigued
    candidates had to be re-admitted because nothing else was available.
    """
    for pool in (base, legacy, fallback):
        filtered = [c for c in pool if c not in fatigued]
        if filtered:
            return filtered, False
    return base, True


def select_hooks(n: int = 3, fallback: list[str] | None = None) -> list[str]:
    """Return the hook pool for the live loop, gated by Phase 7 flags."""
    from core.content.patterns import pattern_store
    from core.creative.hook_performance import hook_fatigue_detector

    fatigue_live = _flag("PHASE7_FATIGUE_DETECTION_LIVE")
    validity_live = _flag("PHASE7_AB_TEST_VALIDITY_LIVE")
    fallback = list(fallback or [])

    legacy = pattern_store.get_top_hooks(n=n) or fallback

    base = pattern_store.get_top_hooks_validated(n=n) if validity_live else legacy
    if not base:
        base = legacy

    if fatigue_live:
        fatigued = set(hook_fatigue_detector.get_fatigued_hooks())
        final, degraded = _select_with_fatigue_ladder(base, legacy, fallback, fatigued)
    else:
        final, degraded = base, False

    _journal_selection("hook", legacy, final, fatigue_live, validity_live, degraded)
    return final


def select_angles(n: int = 3, fallback: list[str] | None = None) -> list[str]:
    """Return the angle pool for the live loop, gated by Phase 7 flags."""
    from core.content.patterns import pattern_store
    from core.creative.sequence_optimizer import sequence_fatigue_optimizer

    fatigue_live = _flag("PHASE7_FATIGUE_DETECTION_LIVE")
    validity_live = _flag("PHASE7_AB_TEST_VALIDITY_LIVE")
    fallback = list(fallback or [])

    legacy = pattern_store.get_top_angles(n=n) or fallback

    base = pattern_store.get_top_angles_validated(n=n) if validity_live else legacy
    if not base:
        base = legacy

    if fatigue_live:
        fatigued = set(sequence_fatigue_optimizer.get_fatigued_sequences())
        final, degraded = _select_with_fatigue_ladder(base, legacy, fallback, fatigued)
    else:
        final, degraded = base, False

    _journal_selection("angle", legacy, final, fatigue_live, validity_live, degraded)
    return final


def record_creative_outcome(hook: str, angle: str, roas: float) -> None:
    """Feed a realized ROAS observation into both fatigue detectors.

    Safe to call unconditionally (regardless of flag state) — recording
    observations never changes behavior on its own, only the gated
    selection functions above do.
    """
    from core.creative.hook_performance import hook_fatigue_detector
    from core.creative.sequence_optimizer import sequence_fatigue_optimizer

    if hook:
        hook_fatigue_detector.record_roas(hook, roas)
    if angle:
        sequence_fatigue_optimizer.update(angle, roas)
