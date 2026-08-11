"""Contract and fixture tests for the gated CJ read-only evidence path."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.adapters.research.cj_readonly_api import (
    CjReadOnlySupplierAdapter,
    explain_cj_read_only_readiness,
    normalize_cj_product,
)
from backend.contracts.adapters import SidecarContext
from backend.mvp_commerce.supplier_evidence import gather_authenticated_supplier_evidence, supplier_evidence_events
from backend.patterns.errors import SupplierQuoteError
from backend.validation.suppliers import CJDropshippingClient
from evaluation.commerce.metrics import supplier_metrics

FIXTURE = Path(__file__).parent / "fixtures" / "supplier_readonly" / "cj_product_response.json"


class FakeClient:
    def __init__(self, fixture: dict):
        self.fixture = fixture
        self.paths: list[str] = []

    def read_only_get(self, path: str, *, params=None, **kwargs):
        self.paths.append(path)
        if path == "/product/list":
            return {"data": self.fixture["list"]}
        if path == "/product/query":
            return {"data": self.fixture["detail"]}
        if path == "/product/stock/queryByVid":
            return {"data": self.fixture["stock"]}
        raise AssertionError(f"unexpected path {path}")


def _env(monkeypatch, **updates):
    for key in ("CJ_EMAIL", "CJ_API_KEY", "MARKETOS_SUPPLIER_AUTH_READONLY", "MARKETOS_SUPPLIER_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    for key, value in updates.items():
        monkeypatch.setenv(key, value)


def test_missing_credentials_fails_closed(monkeypatch):
    _env(monkeypatch, MARKETOS_SUPPLIER_AUTH_READONLY="1")
    result = CjReadOnlySupplierAdapter(client=FakeClient({})).search("espresso", allow_network=True)
    assert result.status == "credential_missing"
    assert result.attempted is False


def test_disabled_flag_fails_closed(monkeypatch):
    _env(monkeypatch, CJ_EMAIL="fixture@example.invalid", CJ_API_KEY="secret", MARKETOS_SUPPLIER_AUTH_READONLY="0")
    result = CjReadOnlySupplierAdapter(client=FakeClient({})).search("espresso", allow_network=True)
    assert result.status == "live_flag_disabled"


def test_network_gate_is_separate_from_credentials(monkeypatch):
    _env(monkeypatch, CJ_EMAIL="fixture@example.invalid", CJ_API_KEY="secret", MARKETOS_SUPPLIER_AUTH_READONLY="1")
    result = CjReadOnlySupplierAdapter(client=FakeClient({})).search("espresso", allow_network=False)
    assert result.status == "network_gate_required"


def test_provider_mismatch_fails_closed(monkeypatch):
    _env(monkeypatch, MARKETOS_SUPPLIER_PROVIDER="zendrop", MARKETOS_SUPPLIER_AUTH_READONLY="1")
    result = CjReadOnlySupplierAdapter(client=FakeClient({})).search("espresso", allow_network=True)
    assert result.status == "provider_mismatch"


def test_normalization_observes_fixture_fields():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    evidence = normalize_cj_product(fixture["list"][0], detail=fixture["detail"], stock=fixture["stock"], observed_at=123.0)
    assert evidence.source == "cj_authenticated_api"
    assert evidence.title == "Portable Espresso Maker"
    assert evidence.price == 12.5
    assert evidence.field_status["price"] == "observed"
    assert evidence.field_status["sku"] == "observed"
    assert evidence.inventory_quantity == 37
    assert evidence.field_status["inventory_quantity"] == "observed"
    assert evidence.field_status["variants"] == "observed"
    assert evidence.field_status["shipping_cost"] == "unavailable"


def test_fixture_adapter_uses_only_read_allowlist(monkeypatch):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    client = FakeClient(fixture)
    _env(monkeypatch, CJ_EMAIL="fixture@example.invalid", CJ_API_KEY="secret", MARKETOS_SUPPLIER_AUTH_READONLY="1")
    result = CjReadOnlySupplierAdapter(client=client, clock=lambda: 123.0).search("espresso", allow_network=True)
    assert result.status == "observed"
    assert result.best and result.best.price == 12.5
    assert set(client.paths) <= {"/product/list", "/product/query", "/product/stock/queryByVid"}
    assert result.to_dict()["mutated"] is False


def test_authenticated_evidence_overrides_economics_assumption(monkeypatch):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    _env(monkeypatch, CJ_EMAIL="fixture@example.invalid", CJ_API_KEY="secret", MARKETOS_SUPPLIER_AUTH_READONLY="1")
    result = gather_authenticated_supplier_evidence(
        "espresso", context=SidecarContext(workspace_id="test", dry_run=False), allow_network=True,
        adapter=CjReadOnlySupplierAdapter(client=FakeClient(fixture), clock=lambda: 123.0),
    )
    assert result.source_type == "authenticated_readonly_api"
    assert result.unit_cost == 12.5
    events = supplier_evidence_events(result, workspace_id="test", run_id="run-1", occurred_at=123.0)
    observed = next(event for event in events if event.event_type == "supplier_product_observed")
    assert observed.metadata["authenticated_readonly"] is True
    assert observed.metadata["no_supplier_mutation_authority"] is True
    assert "secret" not in json.dumps([event.to_dict() for event in events]).lower()


def test_readiness_redacts_credentials(monkeypatch):
    _env(monkeypatch, CJ_EMAIL="real@example.invalid", CJ_API_KEY="super-secret", MARKETOS_SUPPLIER_AUTH_READONLY="1")
    readiness = explain_cj_read_only_readiness()
    encoded = json.dumps(readiness)
    assert readiness["credentials_present_redacted"] is True
    assert "super-secret" not in encoded
    assert "real@example.invalid" not in encoded
    assert readiness["read_only"] is True
    assert readiness["mutated"] is False


def test_malformed_payload_degrades_without_fabricating():
    evidence = normalize_cj_product({"pid": "bad", "sellPrice": "not-a-number"}, detail={}, stock=[])
    assert evidence.price is None
    assert evidence.field_status["price"] == "unavailable"
    assert evidence.field_status["shipping_cost"] == "unavailable"


def test_existing_client_rejects_mutation_endpoint_before_network():
    with pytest.raises(SupplierQuoteError):
        CJDropshippingClient().read_only_get("/order/create", access_token="fixture-token")


def test_evaluation_distinguishes_authenticated_attempt_without_observation():
    metrics, warnings, records = supplier_metrics({}, [{
        "event_type": "supplier_evidence_requested",
        "payload": {"source_type": "authenticated_readonly_api", "status": "credential_missing"},
        "metadata": {"supplier_source": "authenticated_readonly_api"},
    }])
    assert records == []
    assert "no_supplier_product_observed_event" in warnings
    assert metrics["authenticated_supplier_attempted"] == 1
    assert metrics["authenticated_supplier_succeeded"] == 0
    assert metrics["credential_missing_count"] == 1
    assert metrics["supplier_source_distribution"] == {"authenticated_readonly_api": 1}
