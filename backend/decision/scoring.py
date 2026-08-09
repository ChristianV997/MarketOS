import os

_META_TOKEN = os.getenv("META_ACCESS_TOKEN", "")

# ── competition-penalty constants ─────────────────────────────────────────────
# No shadow-mode instrumentation exists yet to calibrate a data-driven
# penalty curve against realized ROAS (unlike the seven flags
# backend/validation/shadow_flag_report.py already tracks), so these stay
# documented, tunable defaults rather than fabricated precision.
#
# COMPETITION_PENALTY_MAX: the penalty ceiling applied to a fully-saturated
# keyword (density=1.0) — kept small relative to typical decision scores so
# competition intel nudges ranking rather than dominating it.
COMPETITION_PENALTY_MAX = float(os.getenv("COMPETITION_PENALTY_MAX", "0.2"))
# COMPETITION_PENALTY_NEUTRAL_DENSITY: the density assumed when the Meta Ads
# Library token is absent or the call fails — "neutral" (neither penalized
# nor rewarded) rather than 0.0, since an unknown competitive landscape
# shouldn't be scored as if no competition exists.
COMPETITION_PENALTY_NEUTRAL_DENSITY = float(os.getenv("COMPETITION_PENALTY_NEUTRAL_DENSITY", "0.5"))


def causal_score(action, graph):
    score = 0
    for (p, c), w in graph.edges.items():
        if p in action:
            score += w
    return score


def competition_penalty(keyword: str, token: str = "") -> float:
    """Return a competition penalty score in [0, COMPETITION_PENALTY_MAX] for
    *keyword*.

    Queries the Meta Ads Library when ``META_ACCESS_TOKEN`` is set; falls
    back to the neutral density when the token is absent or the call fails.
    High ad density → higher penalty → lower final decision score.
    """
    effective_token = token or _META_TOKEN
    if not effective_token:
        return round(COMPETITION_PENALTY_NEUTRAL_DENSITY * COMPETITION_PENALTY_MAX, 4)

    try:
        from connectors.meta_ads_intel import MetaAdsIntel
        score = MetaAdsIntel().competition_score(keyword, effective_token)
        density = float(score.get("density", COMPETITION_PENALTY_NEUTRAL_DENSITY))
    except Exception:
        density = COMPETITION_PENALTY_NEUTRAL_DENSITY

    return round(density * COMPETITION_PENALTY_MAX, 4)

