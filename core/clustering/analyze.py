"""core.clustering.analyze — per-cluster analytics and angle summarisation."""
from __future__ import annotations

from typing import Any

from core.nlp.angles import extract_angles


def analyze_cluster(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate statistics and dominant content angles for a cluster.

    Parameters
    ----------
    cluster:
        List of normalised signal dicts (must contain ``views``, ``likes``,
        ``comments``, and ``text`` keys).

    Returns
    -------
    dict
        ``size``, ``total_views``, ``avg_engagement``, and ``top_angles``.
    """
    if not cluster:
        return {"size": 0, "total_views": 0, "avg_engagement": 0.0, "top_angles": []}

    total_views = sum(int(s.get("views", 0)) for s in cluster)
    avg_engagement = (
        sum(
            (int(s.get("likes", 0)) + int(s.get("comments", 0)))
            / max(int(s.get("views", 0)), 1)
            for s in cluster
        )
        / len(cluster)
    )

    angles: list[str] = []
    for s in cluster:
        angles.extend(extract_angles(s.get("text", "")))

    return {
        "size": len(cluster),
        "total_views": total_views,
        "avg_engagement": avg_engagement,
        "top_angles": list(set(angles)),
    }
