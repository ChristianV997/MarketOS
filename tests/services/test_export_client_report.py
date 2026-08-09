"""Tests for services.reporting.export_client_report + confirms every
service module actually persists its rendered markdown report (Phase 7:
"client report exports"), not just the JSON result.
"""
import os

import backend.core.persistence as pers
import pytest
from backend.workspaces.artifact_store import ArtifactStore
from services.reporting import export_client_report


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", lambda force_refresh=False: [])


def test_returns_none_when_no_report_saved():
    store = ArtifactStore()
    assert export_client_report(store, "ws-1", "exp-missing") is None


class TestEveryServiceModulePersistsAReport:
    def test_product_research(self):
        from services.product_research.audit import run_product_audit
        _, env = run_product_audit("Widget")
        store = ArtifactStore()
        path = export_client_report(store, env.workspace_id, env.experiment_id)
        assert path and os.path.exists(path)
        with open(path, encoding="utf-8") as report_file:
            report_text = report_file.read()
        assert "MarketOS Product & Category Opportunity Audit" in report_text

    def test_unit_economics(self):
        from services.unit_economics.analyzer import run_unit_economics
        _, env = run_unit_economics("Widget", supplier_cost=10.0, retail_price=40.0)
        store = ArtifactStore()
        path = export_client_report(store, env.workspace_id, env.experiment_id)
        assert path and os.path.exists(path)

    def test_creative_growth(self):
        from services.creative_growth.plan import build_creative_growth_plan
        _, env = build_creative_growth_plan("Widget")
        store = ArtifactStore()
        path = export_client_report(store, env.workspace_id, env.experiment_id)
        assert path and os.path.exists(path)

    def test_customer_intelligence(self):
        from services.customer_intelligence.sprint import build_customer_intelligence_sprint
        _, env = build_customer_intelligence_sprint("Shop", vertical="ecommerce_brand")
        store = ArtifactStore()
        path = export_client_report(store, env.workspace_id, env.experiment_id)
        assert path and os.path.exists(path)

    def test_digital_products(self):
        from services.digital_products.plan import build_digital_product_plan
        _, env = build_digital_product_plan("Thing", price=99.0)
        store = ArtifactStore()
        path = export_client_report(store, env.workspace_id, env.experiment_id)
        assert path and os.path.exists(path)

    def test_sales_automation(self):
        from services.sales_automation.simulate import run_sales_bot_simulation
        _, _, _, env = run_sales_bot_simulation("ecommerce_brand", ["hi"])
        store = ArtifactStore()
        path = export_client_report(store, env.workspace_id, env.experiment_id)
        assert path and os.path.exists(path)
