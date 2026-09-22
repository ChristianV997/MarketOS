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
        "eligible": ("screening", "eligible"),
        "draft_ready": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready"),
        "client_review": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review"),
        "approved": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review", "approved"),
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


def test_workbench_route_is_registered(monkeypatch):
    from pathlib import Path

    monkeypatch.delenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", raising=False)
    api_source = Path(__file__).resolve().parents[2] / "backend" / "api.py"
    text = api_source.read_text(encoding="utf-8")
    assert "api.routes.service_delivery_workbench" in text
    assert "include_router(_service_delivery_workbench_router)" in text
    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)
    response = client.get("/api/service-delivery/workbench")
    assert response.status_code == 200
    assert response.json()["live_endpoint"] == "/api/service-delivery/workbench"
    assert response.json()["live_endpoint_status"] == "unavailable"
    denied = client.post("/api/service-delivery/workbench")
    assert denied.status_code == 405


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
        _make_row("product-validation-sprint", "eligible", "client-eligible", currency="USD", registry_path=reg_path),
        _make_row("launch-draft-pack", "client_review", "client-review", currency="CAD", registry_path=reg_path),
        _make_row("managed-acquisition-cro", "approved", "client-approved", currency="MXN", registry_path=reg_path),
        _make_row("unit-economics-cac-roas-diagnostic", "delivered", "client-delivered", currency="USD", registry_path=reg_path),
        _make_row("product-validation-sprint", "rejected", "client-rejected", currency="USD", registry_path=reg_path),
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
    assert len(direct_report["engagements"]) == 11

    # Test via FastAPI TestClient
    app = FastAPI()
    app.include_router(module.router)
    client = TestClient(app)
    response = client.get("/api/service-delivery/workbench")
    assert response.status_code == 200
    http_payload = response.json()
    assert http_payload["live_endpoint_status"] == "available_read_only"
    assert len(http_payload["engagements"]) == 11

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


def _write_projection(monkeypatch, tmp_path, payload: dict, name: str = "projection.json"):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    path = artifacts / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    return path


def _display_economics(currency: str | None, *, contribution: bool):
    fee = None if currency is None else {
        "amount_label": "100",
        "currency": currency,
        "evidence_class": "assumption",
        "source": "backend_service_economics",
        "display_only": True,
    }
    contrib = None
    if contribution and currency is not None:
        contrib = {
            "amount_label": "40",
            "currency": currency,
            "evidence_class": "assumption",
            "source": "backend_service_economics",
            "display_only": True,
        }
    return {
        "authority": "backend_service_economics",
        "frontend_calculates": False,
        "fee": fee,
        "contribution": contrib,
        "contribution_unavailable_reason": None if contrib else "No sanitized contribution copy was supplied.",
        "planning_assumption_note": "Display copies only.",
    }


def _handcrafted_row(
    engagement_id: str,
    lifecycle: str,
    *,
    currency: str | None = "USD",
    contribution: bool = True,
    stale: bool = False,
    client_id: str = "client-a",
):
    return {
        "engagement_id": engagement_id,
        "client_id": client_id,
        "workspace_id": f"ws-{client_id}",
        "service_id": "product-validation-sprint",
        "lifecycle_state": lifecycle,
        "economics": _display_economics(currency, contribution=contribution),
        "financial_readiness": {"ready": contribution, "missing": [], "note": "Display copies only."},
        "stale": stale,
        "next_best_action": {
            "action": "Review",
            "owner": "operator",
            "executes_live_action": False,
            "rationale": "Read-only.",
        },
    }


def _safe_envelope(rows: list, *, availability: str = "manual_import", version: str = "service-delivery-plane-v1"):
    return {
        "schema_version": version,
        "report_version": version,
        "availability": availability,
        "generated_at": "deterministic",
        "read_only": True,
        "network_calls": False,
        "mutated": False,
        "engagements": rows,
        "diagnostics": [],
    }


@pytest.mark.parametrize("lifecycle", [
    "intake", "data_inadequate", "eligible", "draft_ready", "client_review",
    "approved", "delivered", "cancelled", "rejected",
])
def test_workbench_serves_supported_lifecycle_states_without_recalculating(monkeypatch, tmp_path, lifecycle):
    contribution = lifecycle not in {"intake", "data_inadequate", "cancelled", "rejected"}
    row = _handcrafted_row(f"eng-{lifecycle}", lifecycle, contribution=contribution, stale=(lifecycle == "intake"))
    _write_projection(monkeypatch, tmp_path, _safe_envelope([row], availability="partial" if lifecycle == "intake" else "manual_import"))
    app = FastAPI()
    app.include_router(module.router)
    payload = TestClient(app).get("/api/service-delivery/workbench").json()
    assert payload["live_endpoint_status"] == "available_read_only"
    served = payload["engagements"][0]
    assert served["lifecycle_state"] == lifecycle
    assert served["economics"]["frontend_calculates"] is False
    if contribution:
        assert served["economics"]["contribution"]["amount_label"] == "40"
    else:
        assert served["economics"]["contribution"] is None
    if lifecycle == "intake":
        assert served["stale"] is True
        assert payload["availability"] == "partial"


@pytest.mark.parametrize("currency", ["USD", "CAD", "MXN"])
def test_workbench_preserves_currency_labels_without_conversion(monkeypatch, tmp_path, currency):
    row = _handcrafted_row(f"eng-{currency}", "draft_ready", currency=currency)
    _write_projection(monkeypatch, tmp_path, _safe_envelope([row]))
    app = FastAPI()
    app.include_router(module.router)
    served = TestClient(app).get("/api/service-delivery/workbench").json()["engagements"][0]
    assert served["economics"]["fee"]["currency"] == currency
    assert served["economics"]["contribution"]["currency"] == currency


def test_workbench_keeps_missing_contribution_missing(monkeypatch, tmp_path):
    row = _handcrafted_row("eng-missing", "draft_ready", contribution=False)
    _write_projection(monkeypatch, tmp_path, _safe_envelope([row]))
    app = FastAPI()
    app.include_router(module.router)
    served = TestClient(app).get("/api/service-delivery/workbench").json()["engagements"][0]
    assert served["economics"]["fee"]["currency"] == "USD"
    assert served["economics"]["contribution"] is None
    assert served["economics"]["frontend_calculates"] is False


def test_workbench_rejects_currency_mismatch_in_display_economics(monkeypatch, tmp_path):
    row = _handcrafted_row("eng-mix", "draft_ready", currency="USD")
    row["economics"]["contribution"]["currency"] = "CAD"
    _write_projection(monkeypatch, tmp_path, _safe_envelope([row]))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_currency_mismatch" in report["diagnostics"]
    assert report["engagements"] == []


def test_workbench_rejects_duplicate_engagement_ids(monkeypatch, tmp_path):
    rows = [
        _handcrafted_row("eng-dup", "eligible", client_id="client-a"),
        _handcrafted_row("eng-dup", "approved", client_id="client-b"),
    ]
    _write_projection(monkeypatch, tmp_path, _safe_envelope(rows))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_duplicate_engagement_id" in report["diagnostics"]


def test_workbench_rejects_missing_engagement_id(monkeypatch, tmp_path):
    row = _handcrafted_row("eng-ok", "eligible")
    row.pop("engagement_id")
    _write_projection(monkeypatch, tmp_path, _safe_envelope([row]))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_row_missing_engagement_id" in report["diagnostics"]


def test_workbench_rejects_non_object_row(monkeypatch, tmp_path):
    _write_projection(monkeypatch, tmp_path, _safe_envelope(["not-an-object"]))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_row_must_be_object" in report["diagnostics"]


def test_workbench_rejects_oversized_byte_payload(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "huge.json"
    path.write_bytes(b"{" + (b"a" * (module.MAX_PROJECTION_BYTES + 1)))
    monkeypatch.setattr(module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_oversized" in report["diagnostics"]


def test_workbench_rejects_more_than_max_engagements(monkeypatch, tmp_path):
    rows = [
        _handcrafted_row(f"eng-{index}", "eligible", client_id=f"client-{index}")
        for index in range(module.MAX_ENGAGEMENTS + 1)
    ]
    _write_projection(monkeypatch, tmp_path, _safe_envelope(rows))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_oversized" in report["diagnostics"]


def test_workbench_rejects_cross_client_marker_fields(monkeypatch, tmp_path):
    row = _handcrafted_row("eng-cross", "eligible")
    row["cross_client_reference"] = "other-client-id"
    _write_projection(monkeypatch, tmp_path, _safe_envelope([row]))
    report = module.workbench()
    assert report["live_endpoint_status"] == "unavailable"
    assert "service_delivery_projection_failed_workspace_isolation" in report["diagnostics"]
    assert "other-client-id" not in str(report)


def test_workbench_source_order_is_preserved_across_clients(monkeypatch, tmp_path):
    rows = [
        _handcrafted_row("eng-z", "delivered", client_id="client-z"),
        _handcrafted_row("eng-a", "intake", contribution=False, client_id="client-a"),
        _handcrafted_row("eng-m", "client_review", currency="MXN", client_id="client-m"),
    ]
    _write_projection(monkeypatch, tmp_path, _safe_envelope(rows))
    app = FastAPI()
    app.include_router(module.router)
    payload = TestClient(app).get("/api/service-delivery/workbench").json()
    assert [item["engagement_id"] for item in payload["engagements"]] == ["eng-z", "eng-a", "eng-m"]
    assert payload["engagements"][2]["economics"]["fee"]["currency"] == "MXN"


def test_workbench_does_not_claim_live_validation(monkeypatch, tmp_path):
    _write_projection(monkeypatch, tmp_path, _safe_envelope([]))
    payload = module.workbench()
    assert payload["live_endpoint_status"] == "available_read_only"
    assert payload["network_calls"] is False
    assert payload["mutated"] is False
    assert payload.get("availability") != "live_validated"
