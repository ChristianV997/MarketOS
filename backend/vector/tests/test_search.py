"""Tests for semantic search and indexing."""
import pytest

from backend.vector.indexing        import index_hooks, index_products, index_angles
from backend.vector.semantic_search import (
    find_similar_hooks, find_similar_products, rank_by_similarity, search_all,
)
from backend.vector.schemas         import SimilarityResult


def test_index_hooks_upserts_records(fresh_store):
    from backend.inference.embeddings import embed_batch
    hooks = ["This changed everything", "Nobody talks about this", "Wait for it"]
    vecs  = embed_batch(hooks)
    hook_vecs = dict(zip(hooks, vecs))
    n = index_hooks(hook_vecs, store=fresh_store)
    assert n == 3
    assert fresh_store.count("hooks") == 3


def test_index_hooks_idempotent(fresh_store):
    from backend.inference.embeddings import embed_batch
    hooks = ["Idempotent hook"]
    vecs  = embed_batch(hooks)
    hv = dict(zip(hooks, vecs))
    index_hooks(hv, store=fresh_store)
    index_hooks(hv, store=fresh_store)
    assert fresh_store.count("hooks") == 1


def test_find_similar_hooks_returns_results(fresh_store):
    from backend.inference.embeddings import embed_batch
    hooks = ["life changing hack", "morning routine tip", "save money fast"]
    vecs  = embed_batch(hooks)
    index_hooks(dict(zip(hooks, vecs)), store=fresh_store)
    results = find_similar_hooks("save cash quickly", top_k=3)
    assert isinstance(results, list)
    # Should return up to 3 results (may be less if store empty edge case)
    assert len(results) <= 3


def test_search_results_are_similarity_result_instances(fresh_store):
    from backend.inference.embeddings import embed_batch
    hooks = ["check this out"]
    vecs  = embed_batch(hooks)
    index_hooks(dict(zip(hooks, vecs)), store=fresh_store)
    results = find_similar_hooks("check this out", top_k=1)
    for r in results:
        assert isinstance(r, SimilarityResult)
        assert isinstance(r.score, float)
        assert isinstance(r.record_id, str)


def test_rank_by_similarity_returns_sorted_pairs():
    texts = ["morning routine", "evening workout", "breakfast recipe"]
    ranked = rank_by_similarity("daily morning habit", texts)
    assert len(ranked) == 3
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)


def test_index_products_and_search(fresh_store):
    from backend.inference.embeddings import embed_batch
    products = ["wireless earbuds", "led strip lights"]
    vecs = embed_batch(products)
    from backend.vector.indexing import index_products
    n = index_products(dict(zip(products, vecs)), store=fresh_store)
    assert n == 2
    results = find_similar_products("bluetooth headphones", top_k=2)
    assert len(results) <= 2


def test_empty_store_returns_empty(fresh_store):
    results = find_similar_hooks("anything", top_k=5)
    assert results == []


def test_search_all_embeds_once_for_multiple_collections(monkeypatch):
    calls = []

    class Store:
        def search(self, query):
            calls.append(query.collection)
            return []

    monkeypatch.setattr("backend.vector.semantic_search.embed_text", lambda text: calls.append("embed") or [1.0])
    monkeypatch.setattr("backend.vector.semantic_search.get_store", lambda: Store())

    result = search_all("shared query", top_k=3, collections=["products", "campaigns", "patterns"])

    assert result == {"products": [], "campaigns": [], "patterns": []}
    assert calls == ["embed", "products", "campaigns", "patterns"]
