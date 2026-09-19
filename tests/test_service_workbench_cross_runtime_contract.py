"""Real #275 producer → real #271 GET → #277 production adapter (offline).

This test is owned by PR #277. It does not edit the producer or route.
The success-path integration skips when
``evaluation.companyos.service_delivery_projection`` is absent (PR #275).
Unavailable GET cases always run against the real #271 ``workbench()``
handler already stacked on this branch.

Temporary route JSON lives under pytest's tmp_path and is never checked in.
"""
from __future__ import annotations

import json
import os
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import service_delivery_workbench as route_module
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

ROOT = Path(__file__).resolve().parents[1]
CONSUME = ROOT / "frontend" / "tests" / "service-workbench-cross-runtime-consume.mjs"
PACKAGE_IDS = (
    "product-validation-sprint",
    "unit-economics-cac-roas-diagnostic",
    "launch-draft-pack",
    "managed-acquisition-cro",
)
PATH_TO_STATE = {
    "data_inadequate": ("screening", "data_inadequate"),
    "draft_ready": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready"),
    "client_review": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review"),
    "delivered": ("screening", "eligible", "scoped", "evidence_collection", "analysis", "draft_ready", "client_review", "approved", "delivered"),
    "cancelled": ("cancelled",),
    "rejected": ("screening", "rejected"),
}


def _http_get_workbench() -> tuple[int, dict]:
    app = FastAPI()
    app.include_router(route_module.router)
    response = TestClient(app).get("/api/service-delivery/workbench")
    return response.status_code, response.json()


def _consume(payload: dict | None, tmp_path: Path, mode: str = "live-get") -> dict:
    path = tmp_path / "route-response.json"
    if payload is not None:
        path.write_text(json.dumps(payload), encoding="utf-8")
    completed = subprocess.run(
        ["node", "--experimental-strip-types", str(CONSUME), str(path), mode],
        cwd=str(ROOT / "frontend"),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env={**os.environ, "NODE_OPTIONS": ""},
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return json.loads(completed.stdout)


def _assert_fail_closed(consumed: dict) -> None:
    assert consumed["surface"] in {"unavailable", "empty", "blocked"}
    assert consumed["surface"] != "success"
    assert consumed["liveEndpointUnavailable"] is True
    assert consumed["any_live_validated"] is False


def _adequate_intake() -> dict:
    return {name: {"available": True} for name in REQUIRED_CLIENT_DATA_FIELDS}


def _row(package_id: str, target: str, client_id: str, registry_path: str) -> dict:
    producer = pytest.importorskip("evaluation.companyos.service_delivery_projection")
    packages = {item.package_id: item for item in default_service_delivery_packages()}
    pkg = packages[package_id]
    engagement = create_engagement(
        client_id=client_id,
        workspace=ClientWorkspace(name=client_id, workspace_type="client_service"),
        package=pkg,
        scope=f"sanitized {target} record",
    )
    refs = (
        EvidenceRef(
            f"ev-{client_id}",
            source_type="manual_import",
            evidence_state="fixture",
            captured_at="offline-deterministic",
        ),
    )
    if target != "intake":
        for state in PATH_TO_STATE[target]:
            if state == "analysis":
                engagement = transition_engagement(engagement, state, evidence_set=refs)
            else:
                engagement = transition_engagement(engagement, state)
    data_inadequate = target == "data_inadequate"
    dq = assess_client_data_quality({"revenue": {"available": True}} if data_inadequate else _adequate_intake())
    economics = None
    if not dq.data_inadequate and target not in {"cancelled", "rejected", "intake"}:
        economics = evaluate_engagement_economics(
            pkg,
            fee=pkg.price_min_money,
            ad_spend=Money("2000", pkg.currency),
            roas_before=Decimal("1.2"),
            roas_after=Decimal("1.6"),
            cac_before=Money("30", pkg.currency),
            cac_after=Money("24", pkg.currency),
            evidence_refs=refs,
        )
    registry = DeliverableRegistry(path=registry_path)
    deliverable = build_client_service_deliverable(engagement, pkg, economics, dq, recommendation="review", registry=registry)
    artifact = build_service_delivery_artifact(engagement, pkg, economics, dq, deliverable, evidence_refs=refs)
    return producer.build_service_engagement_row(engagement, pkg, dq, economics, artifact)


def test_unconfigured_route_response_is_consumed_unavailable_not_demo(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", raising=False)
    payload = route_module.workbench()
    status, http_payload = _http_get_workbench()
    assert status == 200
    assert http_payload == payload
    assert payload["live_endpoint_status"] == "unavailable"
    assert payload["engagements"] == []
    consumed = _consume(payload, tmp_path)
    _assert_fail_closed(consumed)
    assert consumed["surface"] == "unavailable"
    assert consumed["ids"] == []


def test_malformed_artifact_route_response_stays_unavailable(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(route_module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    payload = route_module.workbench()
    assert payload["live_endpoint_status"] == "unavailable"
    consumed = _consume(payload, tmp_path)
    _assert_fail_closed(consumed)
    assert consumed["surface"] == "unavailable"


def test_empty_object_and_array_artifacts_are_unavailable(monkeypatch, tmp_path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(route_module, "ARTIFACTS", artifacts.resolve())
    empty_object = artifacts / "empty.json"
    empty_object.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(empty_object))
    object_payload = route_module.workbench()
    object_consumed = _consume(object_payload, tmp_path)
    assert object_payload["live_endpoint_status"] == "unavailable"
    _assert_fail_closed(object_consumed)

    empty_array = artifacts / "empty-array.json"
    empty_array.write_text("[]", encoding="utf-8")
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(empty_array))
    array_payload = route_module.workbench()
    array_consumed = _consume(array_payload, tmp_path)
    _assert_fail_closed(array_consumed)


def test_rate_limited_and_unserved_get_never_use_demo(monkeypatch, tmp_path):
    class Denied:
        allowed = False

    monkeypatch.setattr(route_module, "check_rate_limit", lambda policy, key: Denied())
    status, payload = _http_get_workbench()
    assert status == 429
    consumed = _consume(payload, tmp_path)
    _assert_fail_closed(consumed)
    unserved = _consume(None, tmp_path, mode="unserved")
    _assert_fail_closed(unserved)
    assert unserved["used_unserved_envelope"] is True
    http_error = _consume(None, tmp_path, mode="http-error")
    _assert_fail_closed(http_error)
    assert http_error["surface"] == "unavailable"


def test_producer_route_response_is_consumed_by_production_adapter(monkeypatch, tmp_path):
    producer = pytest.importorskip("evaluation.companyos.service_delivery_projection")
    registry_path = str(tmp_path / "deliverables.json")
    rows = [
        _row("product-validation-sprint", "intake", "client-intake", registry_path),
        _row("unit-economics-cac-roas-diagnostic", "data_inadequate", "client-inadequate", registry_path),
        _row("launch-draft-pack", "draft_ready", "client-draft", registry_path),
        _row("managed-acquisition-cro", "client_review", "client-review", registry_path),
        _row("product-validation-sprint", "delivered", "client-delivered", registry_path),
        _row("launch-draft-pack", "cancelled", "client-cancelled", registry_path),
        _row("managed-acquisition-cro", "rejected", "client-rejected", registry_path),
    ]
    envelope = producer.build_service_engagement_projection(
        rows,
        availability="manual_import",
        diagnostics=("offline_sanitized_producer_fixture",),
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    path = artifacts / "projection.json"
    path.write_text(json.dumps(envelope), encoding="utf-8")
    monkeypatch.setattr(route_module, "ARTIFACTS", artifacts.resolve())
    monkeypatch.setenv("MARKETOS_SERVICE_DELIVERY_PROJECTION", str(path))
    direct = route_module.workbench()
    status, payload = _http_get_workbench()
    assert status == 200
    assert payload == direct
    assert payload["live_endpoint_status"] == "available_read_only"
    assert payload["live_endpoint"] == "/api/service-delivery/workbench"
    assert payload["schema_version"] == "service-delivery-plane-v1"
    assert [row["package_id"] for row in payload["engagements"]] == [row["package_id"] for row in rows]
    consumed = _consume(payload, tmp_path)
    assert consumed["rejected"] is False
    assert consumed["input_contract"] == "service-delivery-plane-v1"
    assert consumed["live_endpoint_status"] == "available_read_only"
    assert consumed["surface"] != "success"
    assert consumed["ids"] == [row["engagement_id"] for row in payload["engagements"]]
    assert set(consumed["services"]) >= set(PACKAGE_IDS)
    assert consumed["lifecycles"][0] == "intake"
    assert consumed["lifecycles"][1] == "data_inadequate"
    assert "draft_ready" in consumed["lifecycles"]
    assert "client_review" in consumed["lifecycles"]
    assert "delivered" in consumed["lifecycles"]
    assert "cancelled" in consumed["lifecycles"]
    assert "rejected" in consumed["lifecycles"]
    assert consumed["data_inadequate"][1] is True
    assert consumed["missing_data"][1]
    assert all(flag is False for flag in consumed["frontend_calculates"])
    assert all(authority == "backend_service_economics" for authority in consumed["economics_authority"])
    assert consumed["any_live_validated"] is False
    assert "live_validated" not in consumed["evidence_classes"]
    draft_index = consumed["lifecycles"].index("draft_ready")
    assert consumed["fees"][draft_index]
    assert consumed["currencies"][draft_index]
    assert consumed["lifecycles"][1] == "data_inadequate"
