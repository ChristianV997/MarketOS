from __future__ import annotations

import os
from copy import deepcopy

_ROAS_WIN = float(os.getenv("CONTENT_ROAS_WIN", "1.5"))
_CTR_WIN  = float(os.getenv("CONTENT_CTR_WIN",  "0.02"))
_CVR_WIN  = float(os.getenv("CONTENT_CVR_WIN",  "0.015"))
_ENG_WIN  = float(os.getenv("CONTENT_ENG_WIN",  "0.04"))

# Minimum reach before organic engagement counts as a real signal — high
# engagement on a handful of impressions is noise, not a winner.
_ORGANIC_MIN_IMPRESSIONS = int(os.getenv("ORGANIC_MIN_IMPRESSIONS", "1000"))

# Reference ceiling values used for 0-1 normalisation
_ROAS_REF = 3.0
_CTR_REF  = 0.10
_CVR_REF  = 0.05
_ENG_REF  = 0.15


def engagement_score(event: dict) -> float:
    """Composite 0–1 score weighted toward ROAS."""
    roas = min(event.get("roas", 0.0) / _ROAS_REF, 1.0)
    ctr  = min(event.get("ctr",  0.0) / _CTR_REF,  1.0)
    cvr  = min(event.get("cvr",  0.0) / _CVR_REF,  1.0)
    eng  = min(event.get("engagement_rate", 0.0) / _ENG_REF, 1.0)
    return round(0.4 * roas + 0.3 * ctr + 0.2 * cvr + 0.1 * eng, 4)


def classify_video(event: dict) -> str:
    """Classify a single content event as WINNER, LOSER, or NEUTRAL.

    Organic events (source="organic") are classified on engagement alone:
    they carry no ROAS/CTR by nature, and running them through the paid
    branch would mark every organic post a LOSER (roas=0) and poison
    PatternStore with false negative evidence. Absence of purchase signal
    is not negative evidence — organic can only be WINNER or NEUTRAL.
    """
    if event.get("source") == "organic":
        eng = float(event.get("engagement_rate", 0.0) or 0.0)
        impressions = int(event.get("impressions", 0) or 0)
        if eng >= _ENG_WIN and impressions >= _ORGANIC_MIN_IMPRESSIONS:
            return "WINNER"
        return "NEUTRAL"

    roas = event.get("roas", 0.0)
    ctr  = event.get("ctr",  0.0)
    cvr  = event.get("cvr",  0.0)
    if roas >= _ROAS_WIN and (ctr >= _CTR_WIN or cvr >= _CVR_WIN):
        return "WINNER"
    if roas < 0.8 and ctr < _CTR_WIN * 0.5:
        return "LOSER"
    return "NEUTRAL"


def batch_classify(events: list[dict]) -> list[dict]:
    """Annotate each event with 'label' and 'eng_score'. Winners are stored in
    creative_memory for vector-similarity retrieval.

    Returns a new list of annotated dicts (originals are not mutated).
    """
    annotated = []
    for raw in events:
        e = deepcopy(raw)
        label = classify_video(e)
        e["label"] = label
        e["eng_score"] = engagement_score(e)
        annotated.append(e)

    # Store winners in vector memory for similarity-guided generation
    winners = [e for e in annotated if e["label"] == "WINNER"]
    if winners:
        try:
            from core.creative.embedding import embed_creative
            from core.memory.creative_memory import CreativeMemory
            _cm = _get_creative_memory()
            for w in winners:
                script = w.get("hook", "") + " " + w.get("angle", "")
                embedding = embed_creative(script)
                _cm.add(embedding, {
                    "product":    w.get("product", ""),
                    "hook":       w.get("hook", ""),
                    "angle":      w.get("angle", ""),
                    "roas":       w.get("roas", 0.0),
                    "eng_score":  w["eng_score"],
                })
        except Exception:
            pass

    return annotated


# Module-level CreativeMemory singleton shared with the rest of core/
def _get_creative_memory():
    try:
        from core.memory import _creative_memory  # type: ignore[attr-defined]
        return _creative_memory
    except Exception:
        pass
    # Fallback: maintain a local instance
    global _local_cm
    if "_local_cm" not in globals():
        from core.memory.creative_memory import CreativeMemory
        globals()["_local_cm"] = CreativeMemory()
    return globals()["_local_cm"]
