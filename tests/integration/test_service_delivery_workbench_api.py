from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import service_delivery_workbench as module
try:
    from backend.deliverables.registry import DeliverableRegistry
    from backend.economics import EvidenceRef, Money
    from backend.workspaces.client_workspace import ClientWorkspace
    from evaluation.companyos.service_delivery import (
        REQUIRED_CLIENT_DATA_FIELDS,
        assess_client_data_quality,
        build_client_service_deliverable,
        create_engagement,
        default_service_delivery_packages,
        evaluate_engagement_economics,
        transition_engagement,
    )
    from evaluation.companyos.service_delivery_artifact import build_service_delivery_artifact
    from evaluation.companyos.service_delivery_projection import (
        build_service_engagement_projection,
        build_service_engagement_row,
    )
    _HAS_PRODUCER = True
except ImportError:
    _HAS_PRODUCER = False


def _adequate_intake() -> dict:
    return {name: {"available": True} for name in REQUIRED_CLIENT_DATA_FIELDS}


def _make_row(package_id: str, target_state: str, client_id: str, *, currency: str = "USD", registry_path: str) -> dict:
    packages = {p.package_id: p for p in default_service_delivery_packages()}
    pkg = packages[package_id]
    workspace = ClientWorkspace(name=client_id, workspace_type="client_service")
    engagement = create_engagement(client_id=client_id, workspace=workspace, package=pkg, scope=f"scope for {client_id}")
    refs = (EvidenceRef(f"ev-{client_id}", source_type="order_export", evidence_state="live_readonly", captured_at="2026-09-01"),)
    path_to_state = {
        "intake": (),
        "data_inadequate": ("screening", "data_inadequate"),
        "draft_ready": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready"),
        "client_review": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review"),
        "delivered": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review", "approved", "delivered"),
        "cancelled": ("cancelled",),
        "rejected": ("screening", "rejected"),
    }
    for state in path_to_state[target_state]:
        if state == "analysis":
            engagement = transition_engagement(engagement, state, evidence_set=refs)
        else:
            engagement = transition_engagement(engagement, state)
    data_inadequate = target_state == "data_inadequate"
    dq = assess_client_data_quality({"revenue": {"available": True}} if data_inadequate else _adequate_intake())
    economics = None
    if not dq.data_inadequate and target_state not in {"cancelled", "rejected", "intake"}:
        economics = evaluate_engagement_economics(
            pkg,
            fee=Money(str(pkg.price_min_money.amount), currency),
            ad_spend=Money("2000", currency),
            roas_before=Decimal("1.4"),
            roas_after=Decimal("2.1"),
            cac_before=Money("22", currency),
            cac_after=Money("16", currency),
            labor_cost=Money(str(pkg.labor_cost.amount), currency),
            tooling_cost=Money(str(pkg.tooling_cost.amount), currency),
            pass_through_cost=Money(str(pkg.optional_pass_through_cost.amount), currency),
            refund_revision_reserve=Money(str(pkg.refund_revision_reserve.amount), currency),
            evidence_refs=refs,
        )
    registry = DeliverableRegistry(path=registry_path)
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="ok", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, evidence_refs=refs)
    return build_service_engagement_row(engagement, pkg, dq, economics, artifact)


def test_workbench_is_safe_and_unavailable_without_projection(monkeypatch):
    monkeypatch.delenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", raising=False)
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert report["read_only"] is True
    assert report["network_calls"] is False
    assert report["mutated"] is False
    assert report["engagements"] == []


def test_workbench_rejects_projection_outside_artifacts(monkeypatch, tmp_path):
    path = tmp_path / "projection.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert report["diagnostics"] == ["service_delivery_projection_not_configured"]


def test_workbench_accepts_safe_read_only_projection(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "service_projection.json"
    path.write_text(json.dumps({"schema_version": "service-engagement-projection-v1", "availability": "manual_import", "generated_at": "deterministic", "read_only": True, "network_calls": False, "mutated": False, "engagements": []}), encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "available_read_only"
    assert report["live_endpoint"] == "/api/service-delivery/workbench"
    assert "read_only_artifact_projection" in report["diagnostics"]


def test_workbench_rejects_internal_fields(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "unsafe.json"
    path.write_text(json.dumps({"schema_version": "service-engagement-projection-v1", "read_only": True, "network_calls": False, "mutated": False, "engagements": [], "internal_prompt": "do not export"}), encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "internal_prompt" not in str(report)


def test_workbench_route_is_registered():
    from backend.api import app
    paths = set()
    for route in app.routes:
        if getattr(route, "path", None):
            paths.add(route.path)
        original = getattr(route, "original_router", None)
        paths.update(item.path for item in getattr(original, "routes", ()) if getattr(item, "path", None))
    assert "/api/service-delivery/workbench" in paths


@pytest.mark.skipif(not _HAS_PRODUCER, reason="evaluation.companyos.service_delivery_projection not available on this branch")
def test_workbench_end_to_end_real_producer_all_priority_packages(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "projection.json"
    reg_path = str(tmp_path / "deliverables.json")

    rows = [
        _make_row("product-validation-sprint", "draft_ready", "client-usd", currency="USD", registry_path=reg_path),
        _make_row("unit-economics-cac-roas-diagnostic", "data_inadequate", "client-inadequate", currency="USD", registry_path=reg_path),
        _make_row("launch-draft-pack", "draft_ready", "client-cad", currency="CAD", registry_path=reg_path),
        _make_row("managed-acquisition-cro", "draft_ready", "client-mxn", currency="MXN", registry_path=reg_path),
        _make_row("product-validation-sprint", "intake", "client-intake", currency="USD", registry_path=reg_path),
        _make_row("launch-draft-pack", "cancelled", "client-cancelled", currency="USD", registry_path=reg_path),
    ]
    real_projection = build_service_engagement_projection(
        rows,
        availability="manual_import",
        diagnostics=("end_to_end_real_producer_test",),
    )
    path.write_text(json.dumps(real_projection), encoding="utf-8")

    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))

    direct_report = module.workbench()
    assert direct_report["live_endpoint_status"] == "available_read_only"
    assert direct_report["read_only"] is True
    assert direct_report["network_calls"] is False
    assert direct_report["mutated"] is False
    assert len(direct_report["engagements"]) == 6

    # Test via FastAPI TestClient
    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)
    response = client.get("/api/service-delivery/workbench")
    assert response.status_code == 200
    http_payload = response.json()
    assert http_payload["live_endpoint_status"] == "available_read_only"
    assert len(http_payload["engagements"]) == 6

    # Verify server ordering
    assert [e["engagement_id"] for e in http_payload["engagements"]] == [r["engagement_id"] for r in rows]

    # Verify currencies preserved
    currencies = [e["economics"]["fee"]["currency"] for e in http_payload["engagements"]]
    assert currencies[0] == "USD"
    assert currencies[2] == "CAD"
    assert currencies[3] == "MXN"

    # Verify data_inadequate and intake do not have ready status
    assert http_payload["engagements"][1]["financial_readiness"]["ready"] is False
    assert http_payload["engagements"][1]["economics"]["contribution"] is None
    assert http_payload["engagements"][4]["financial_readiness"]["ready"] is False
    assert http_payload["engagements"][4]["economics"]["contribution"] is None


def test_workbench_enforces_rate_limiting_429(monkeypatch):
    class Denied:
        allowed = False

    monkeypatch.setattr(module, "check_rate_limit", lambda policy, key: Denied())
    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)
    response = client.get("/api/service-delivery/workbench")
    assert response.status_code == 429
    data = response.json()
    assert data["status"] == "rate_limited"
    assert data["read_only"] is True
    assert data["mutated"] is False


@pytest.mark.parametrize("traversal_path", [
    "../../etc/passwd",
    "../outside.json",
    "nested/../../outside.json",
])
def test_workbench_rejects_adversarial_traversal_paths(monkeypatch, tmp_path, traversal_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    target = (artifacts / traversal_path).resolve()
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(target))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert report["diagnostics"] == ["service_delivery_projection_not_configured"]


def test_workbench_rejects_directory_as_projection_path(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(artifacts))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert report["diagnostics"] == ["service_delivery_projection_not_configured"]


@pytest.mark.parametrize("bad_content,expected_diagnostic", [
    ("not valid json {", "service_delivery_projection_unavailable"),
    ("", "service_delivery_projection_unavailable"),
    ("[1, 2, 3]", "service_delivery_projection_root_must_be_object"),
    ("\"just a string\"", "service_delivery_projection_root_must_be_object"),
    (json.dumps({"schema_version": "invalid-version-v9", "read_only": True, "engagements": []}), "unsupported_service_delivery_projection"),
    (json.dumps({"schema_version": "service-delivery-plane-v1", "read_only": False, "engagements": []}), "unsafe_service_delivery_projection"),
    (json.dumps({"schema_version": "service-delivery-plane-v1", "read_only": True, "network_calls": True, "engagements": []}), "unsafe_service_delivery_projection"),
    (json.dumps({"schema_version": "service-delivery-plane-v1", "read_only": True, "mutated": True, "engagements": []}), "unsafe_service_delivery_projection"),
    (json.dumps({"schema_version": "service-delivery-plane-v1", "read_only": True, "engagements": "not-a-list"}), "service_delivery_projection_rows_must_be_array"),
])
def test_workbench_handles_all_malformed_json_variants(monkeypatch, tmp_path, bad_content, expected_diagnostic):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "corrupt.json"
    path.write_text(bad_content, encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert expected_diagnostic in report["diagnostics"]


def test_workbench_rejects_deeply_nested_leakage_inside_engagements(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "nested_leak.json"
    leaking_payload = {
        "schema_version": "service-delivery-plane-v1",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "engagements": [
            {
                "engagement_id": "eng-1",
                "intake": {
                    "client_id": "c1",
                    "fields": [],
                    "operator_secret_note": "sk-live-999988887777",
                },
            }
        ],
    }
    path.write_text(json.dumps(leaking_payload), encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_failed_workspace_isolation" in report["diagnostics"]
    assert "sk-live" not in str(report)
