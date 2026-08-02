from __future__ import annotations

import json

import pytest

from backend.contracts.adapters import SidecarContext
from backend.research.cache import ResearchCache
from backend.research.mode import ResearchOnlyError
from services.product_research.dossier_store import DossierStore
from services.product_research.dossiers import ApprovalRequest, CategoryDossier, EvidenceRecord, ProductDossier, SupplierEvidence
from services.product_research.portfolio import optimize_top_three, simulate_product, tipping_point
from services.product_research.run import ResearchRunConfig, run_category_research
from services.product_research.launch_gate import evaluate_launch_gate


def test_sidecar_context_blocks_live_write_in_research_mode(monkeypatch):
    monkeypatch.setenv("MARKETOS_RESEARCH_ONLY", "true")
    with pytest.raises(ResearchOnlyError):
        SidecarContext(dry_run=False, approval_state="approved", idempotency_key="x").require_live_idempotency()


def test_dossier_store_is_atomic_and_idempotent(tmp_path):
    store = DossierStore(tmp_path / "dossiers.json")
    dossier = CategoryDossier(category="fitness", products=(ProductDossier(name="bands", category="fitness"),))
    store.save_dossier(dossier)
    store.save_dossier(dossier)
    approval = ApprovalRequest("brand", "brand_1", "create_brand")
    store.save_approval(approval)
    snapshot = store.snapshot()
    assert len(snapshot["dossiers"]) == 1
    assert len(snapshot["approvals"]) == 1
    assert json.loads((tmp_path / "dossiers.json").read_text())["dossiers"]


def test_research_cache_expires_and_tracks_health(tmp_path):
    cache = ResearchCache(tmp_path / "cache.json")
    cache.put("k", {"value": 1})
    assert cache.get("k", ttl_s=60) == {"value": 1}
    cache.record_source("source", ok=True, duration_s=0.2, count=2)
    assert cache.health()["source"]["success_rate"] == 1.0


def test_research_run_is_bounded_and_research_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKETOS_RESEARCH_ONLY", "true")
    dossier = run_category_research(
        ResearchRunConfig("fitness", max_products=2),
        cache=ResearchCache(tmp_path / "cache.json"),
        store=DossierStore(tmp_path / "dossiers.json"),
    )
    assert dossier.status == "research_only"
    assert len(dossier.products) <= 2
    assert dossier.portfolio["method"] == "research_only"
    assert dossier.tipping_point["status"] in {"candidate", "watch", "reject", "insufficient_evidence"}
    assert all(product.experiment_matrix for product in dossier.products)


def test_portfolio_and_scenarios_are_deterministic():
    offers = (SupplierEvidence("s1", "Supplier", "p", unit_cost=5, shipping_cost=2, landed_cost=7),)
    products = (
        ProductDossier(name="a", category="fitness", supplier_offers=offers, score=.8),
        ProductDossier(name="b", category="fitness", supplier_offers=offers, score=.7),
    )
    first = simulate_product(products[0], samples=50)
    second = simulate_product(products[0], samples=50)
    assert first == second
    portfolio = optimize_top_three(products)
    assert portfolio["products"] == [products[0].product_id, products[1].product_id]
    assert tipping_point(products, [first])


def test_launch_gate_requires_all_human_approvals_and_research_exit(monkeypatch):
    monkeypatch.setenv("MARKETOS_RESEARCH_ONLY", "true")
    approvals = [{"subject_id": "b", "subject_type": kind, "state": "approved"}
                 for kind in ("brand", "inventory", "landing_page", "social_account", "ads")]
    result = evaluate_launch_gate("b", dossier={"tipping_point": {"status": "candidate"}},
                                 approvals=approvals, credentials_ready=True, budget_ready=True)
    assert result["allowed"] is False
    assert "research_only" in result["reasons"]
