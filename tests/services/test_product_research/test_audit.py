"""Tests for services.product_research.audit.run_product_audit."""
import backend.core.persistence as pers
import pytest
from backend.workspaces.client_workspace import ClientWorkspace
from services.product_research.audit import run_product_audit
from services.product_research.schemas import ProductAuditResult


def _fake_signals(force_refresh=False):
    return [{"product": "Widget", "score": 0.8, "source": "mock", "platform": "mock"}]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(pers, "STATE_DIR", str(tmp_path))
    # Same interception point tests/test_dropship_discovery.py uses to keep
    # discover_products' own dedup/scoring/registration logic real while
    # avoiding the network-touching adapter fetch path underneath it.
    from core.signals import signal_engine
    monkeypatch.setattr(signal_engine, "get", _fake_signals)


class TestProductAuditStructure:
    def test_returns_result_and_envelope_with_expected_fields(self):
        result, envelope = run_product_audit("Widget", category="general")

        assert isinstance(result, ProductAuditResult)
        assert result.product_name == "Widget"
        assert result.recommendation in ("green", "yellow", "red", "unknown")
        assert envelope.service_name == "product_research"
        assert envelope.status == "completed"

    def test_data_provenance_reports_source_status(self):
        result, _ = run_product_audit("Widget")
        names = {row["name"] for row in result.data_provenance}
        assert names  # discovery_registry.status_report() is populated by adapter self-registration


class TestProductAuditDryRunDisclaimer:
    def test_markdown_contains_dry_run_disclaimer_by_default(self):
        from services.product_research.report import render_product_audit_markdown
        result, _ = run_product_audit("Widget")
        md = render_product_audit_markdown(result)
        assert "DRY RUN" in md

    def test_markdown_omits_disclaimer_when_not_dry_run(self):
        from services.product_research.report import render_product_audit_markdown
        ws = ClientWorkspace(name="live-ws", dry_run_default=False)
        result, _ = run_product_audit("Widget", workspace=ws)
        md = render_product_audit_markdown(result)
        assert "DRY RUN" not in md


class TestProductAuditEnvelope:
    def test_envelope_registered_and_retrievable(self):
        from backend.experiments.registry import get_experiment_registry
        result, envelope = run_product_audit("Widget")
        fetched = get_experiment_registry().get(envelope.experiment_id)
        assert fetched is not None
        assert fetched.status == "completed"

    def test_audit_log_refs_populated(self):
        from backend.experiments.audit_log import transitions_for
        _, envelope = run_product_audit("Widget")
        assert envelope.audit_log_refs
        events = transitions_for(envelope)
        event_names = {e["event"] for e in events}
        assert "experiment_created" in event_names
        assert "experiment_completed" in event_names


class TestProductAuditNeverRaises:
    def test_never_raises_when_no_supplier_found(self, monkeypatch):
        # validator.py binds find_best_supplier at module-import time
        # (`from backend.validation.suppliers import find_best_supplier`),
        # so it must be patched on the validator module itself, not on
        # backend.validation.suppliers.
        monkeypatch.setattr("backend.validation.validator.find_best_supplier", lambda *a, **k: None)
        result, envelope = run_product_audit("Nonexistent Product X")
        assert result.recommendation == "red"
        assert envelope.status == "completed"

    def test_never_raises_when_discovery_context_fails(self, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("network unavailable")
        monkeypatch.setattr("backend.discovery.discover_products", _boom)
        result, envelope = run_product_audit("Widget")
        assert isinstance(result, ProductAuditResult)
        assert envelope.status == "completed"
