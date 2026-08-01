"""core.clustering.kmeans — k-means clustering for embedding vectors."""
from __future__ import annotations

from typing import Any


def cluster(vectors: list[list[float]], k: int = 5) -> list[int]:
    """Assign each vector in *vectors* to one of *k* clusters.

    Uses ``scikit-learn`` KMeans when available; falls back to assigning
    labels by index modulo *k* when the library is absent.

    Parameters
    ----------
    vectors:
        List of equal-length float vectors.
    k:
        Number of clusters.

    Returns
    -------
    list[int]
        Cluster label (0 .. k-1) for each input vector.
    """
    if not vectors:
        return []
    try:
        from sklearn.cluster import KMeans  # type: ignore[import]
        import numpy as np  # type: ignore[import]

        km = KMeans(n_clusters=min(k, len(vectors)), random_state=42, n_init="auto")
        labels = km.fit_predict(np.array(vectors))
        return [int(l) for l in labels]
    except Exception:
        return [i % k for i in range(len(vectors))]
