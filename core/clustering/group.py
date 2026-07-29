"""core.clustering.group — group signals by cluster label."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def group_by_cluster(
    signals: list[dict[str, Any]], labels: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """Group *signals* according to their cluster *labels*.

    Parameters
    ----------
    signals:
        List of signal dicts.
    labels:
        Integer label for each signal (same order as *signals*).

    Returns
    -------
    dict[int, list[dict]]
        Mapping from cluster id to the list of signals in that cluster.
    """
    clusters: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for s, l in zip(signals, labels):
        clusters[l].append(s)
    return dict(clusters)
