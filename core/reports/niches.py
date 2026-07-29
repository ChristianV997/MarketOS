"""core.reports.niches — niche discovery output from cluster analysis."""
from __future__ import annotations

from typing import Any

from core.clustering.analyze import analyze_cluster


def discover(clusters: dict[int, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """Analyse each cluster and return niches sorted by total views.

    Parameters
    ----------
    clusters:
        Mapping from cluster id to list of signal dicts, as produced by
        :func:`~core.clustering.group.group_by_cluster`.

    Returns
    -------
    list[dict]
        Niche dicts (``cluster_id`` + analysis fields) sorted by
        descending ``total_views``.
    """
    results = []
    for cid, cluster in clusters.items():
        analysis = analyze_cluster(cluster)
        results.append({"cluster_id": cid, **analysis})
    return sorted(results, key=lambda x: x["total_views"], reverse=True)
