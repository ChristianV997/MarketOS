"""backend.decision.organic_gate — blend organic validation evidence into
the paid-launch confidence gate.

Before this module, Playbook.confidence only ever grew from paid-ad
evidence (evidence_count is fed by classified paid engagement events) —
Commerce Phase E's organic posting produces real engagement data
(backend.organic.engagement.product_engagement) but nothing about it fed
into whether a product's paid campaign gets a green light. That wastes ad
spend launching on products organic evidence already showed were weak,
and under-launches products organic already validated well.

gate_launch(playbook) blends paid evidence_count with organic-derived
pseudo-evidence (posts * mean engagement rate, gated on a minimum reach so
a single lucky post can't dominate the blend), using the same shrinkage
formula PlaybookMemory already uses for its own confidence
(evidence / (evidence + 10)). Always journals shadow_organic_gate (legacy
paid-only vs blended verdict, side by side); returns the legacy verdict
unless ORGANIC_GATE_LIVE=true, so nothing changes for the existing
_run_scaling launch path until the flag flips.
"""
from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

# How many "evidence units" one organic post's engagement is worth,
# relative to one paid observation — organic data is a weaker, noisier
# signal (no spend behind it to confirm intent), so it's discounted.
_ORGANIC_EVIDENCE_WEIGHT = float(os.getenv("ORGANIC_EVIDENCE_WEIGHT", "0.5"))
# Below this total impressions, organic engagement_rate is too noisy to
# trust (a single post reaching 50 people can show 20% engagement by luck).
_ORGANIC_MIN_REACH = int(os.getenv("ORGANIC_MIN_REACH", "1000"))
_LAUNCH_CONFIDENCE_THRESHOLD = float(os.getenv("PLAYBOOK_LAUNCH_CONFIDENCE", "0.6"))


def _live() -> bool:
    return os.getenv("ORGANIC_GATE_LIVE", "false").lower() == "true"


def organic_evidence(product: str) -> dict[str, Any]:
    """The organic engagement rollup for *product* — must be keyed exactly
    as backend.organic.poster posted it (the full generated listing title,
    not necessarily the raw discovery product name; callers resolving from
    a catalog entry should pass entry.title). Returns {posts, impressions,
    mean_engagement_rate}; zeros (never raises) if unavailable."""
    try:
        from backend.organic.engagement import product_engagement
        return product_engagement(product)
    except Exception as exc:
        _log.debug("organic_evidence_lookup_failed product=%s error=%s", product, exc)
        return {"posts": 0, "impressions": 0, "mean_engagement_rate": 0.0}


def blended_confidence(playbook: Any) -> tuple[float, dict[str, Any]]:
    """Return (blended_confidence, detail) — detail carries both the
    legacy paid-only confidence and the organic pseudo-evidence, for the
    shadow journal."""
    paid_evidence = float(getattr(playbook, "evidence_count", 0))
    legacy_confidence = float(getattr(playbook, "confidence", 0.0))

    organic = organic_evidence(getattr(playbook, "product", ""))
    reach_ok = organic["impressions"] >= _ORGANIC_MIN_REACH
    # x10 scales a 0-1 engagement_rate into the same rough magnitude as a
    # paid evidence count (each post-worth of engagement ~ up to 10 "units"
    # at 100% engagement, which never happens — realistic rates land it
    # well below one full paid observation per post, as intended).
    organic_units = (
        _ORGANIC_EVIDENCE_WEIGHT * organic["posts"] * organic["mean_engagement_rate"] * 10
        if reach_ok else 0.0
    )
    blended = round(
        (paid_evidence + organic_units) / (paid_evidence + organic_units + 10), 4
    )

    return blended, {
        "legacy_confidence": legacy_confidence,
        "blended_confidence": blended,
        "paid_evidence": paid_evidence,
        "organic_units": round(organic_units, 4),
        "organic_posts": organic["posts"],
        "organic_impressions": organic["impressions"],
        "organic_engagement_rate": organic["mean_engagement_rate"],
        "reach_gate_passed": reach_ok,
    }


def gate_launch(playbook: Any, threshold: float = _LAUNCH_CONFIDENCE_THRESHOLD) -> bool:
    """Should *playbook* clear the bar to launch/relaunch a paid campaign?

    Always computes and journals both the legacy (paid-only confidence)
    and blended (paid+organic) verdicts as shadow_organic_gate; returns
    the blended verdict only when ORGANIC_GATE_LIVE=true (default false),
    else the legacy verdict — today's exact behavior.
    """
    blended, detail = blended_confidence(playbook)
    legacy_verdict = detail["legacy_confidence"] >= threshold
    blended_verdict = blended >= threshold

    _journal(playbook, detail, legacy_verdict, blended_verdict, threshold)
    return blended_verdict if _live() else legacy_verdict


def _journal(playbook: Any, detail: dict, legacy_verdict: bool,
            blended_verdict: bool, threshold: float) -> None:
    try:
        from backend.orchestration.event_store import event_store, new_workflow_id
        event_store.append(
            new_workflow_id("organicgate"), "shadow_organic_gate",
            workflow="organic_gate", step="gate_launch",
            data={"product": getattr(playbook, "product", ""), "threshold": threshold,
                 "legacy_verdict": legacy_verdict, "blended_verdict": blended_verdict,
                 "live": _live(), **detail},
        )
    except Exception:
        _log.warning("organic_gate_journal_failed product=%s",
                    getattr(playbook, "product", ""), exc_info=True)


__all__ = ["gate_launch", "blended_confidence", "organic_evidence"]
