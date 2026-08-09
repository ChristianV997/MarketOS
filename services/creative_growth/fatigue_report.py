"""services.creative_growth.fatigue_report — analyze_creative_fatigue.

Wraps core.creative.hook_performance.hook_fatigue_detector and
core.creative.sequence_optimizer.sequence_fatigue_optimizer — the same
rolling-window fatigue detectors the live orchestrator loop already uses,
no new fatigue math.
"""
from __future__ import annotations

from typing import Any


def analyze_creative_fatigue(hooks: list[str], angles: list[str]) -> dict[str, Any]:
    """Never raises."""
    hook_reports: list[dict[str, Any]] = []
    angle_reports: list[dict[str, Any]] = []

    try:
        from core.creative.hook_performance import hook_fatigue_detector
        for hook in (hooks or []):
            hook_reports.append(hook_fatigue_detector.get_fatigue_metrics(hook))
    except Exception:
        pass

    try:
        from core.creative.sequence_optimizer import sequence_fatigue_optimizer
        for angle in (angles or []):
            angle_reports.append({
                "angle": angle,
                "is_fatigued": sequence_fatigue_optimizer.is_fatigued(angle),
                "recent_roas_7d": sequence_fatigue_optimizer.get_recent_roas(angle),
                "historical_roas": sequence_fatigue_optimizer.get_historical_roas(angle),
            })
    except Exception:
        pass

    fatigued_hooks = [r["hook"] for r in hook_reports if r.get("is_fatigued")]
    fatigued_angles = [r["angle"] for r in angle_reports if r.get("is_fatigued")]

    return {
        "hook_reports": hook_reports,
        "angle_reports": angle_reports,
        "fatigued_hooks": fatigued_hooks,
        "fatigued_angles": fatigued_angles,
        "refresh_needed": bool(fatigued_hooks or fatigued_angles),
    }
