"""Composition regressions for the TikTok retirement + route-gate + evidence vertical.

Owned by PR #494 only. These tests must pass on #494 alone (composition-dependent
cases skip) and enforce the joint vertical when #459/#468 are also present.

Never edits #459/#468 paths. No network, credentials, or TikTok provider calls.
"""
from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

from backend.adapters.research import tiktok_research_evidence as bridge
from backend.contracts.adapters import SidecarContext
from evaluation.commerce.tiktok_research_evidence import (
    ACCESS_DATE,
    COMMERCIAL_INELIGIBILITY,
    FakeTikTokResearchTransport,
    build_tiktok_research_evidence,
    official_citations,
    research_tool_capabilities,
)

ROOT = Path(__file__).resolve().parents[1]
LEGACY_CLIENT = ROOT / "core" / "sensors" / "tiktok_client.py"
LEGACY_CONNECTOR = ROOT / "connectors" / "tiktok_connector.py"
ROUTE = ROOT / "api" / "routes" / "tiktok.py"
EVIDENCE_MODS = (
    ROOT / "evaluation" / "commerce" / "tiktok_research_evidence.py",
    ROOT / "backend" / "adapters" / "research" / "tiktok_research_evidence.py",
    ROOT / "scripts" / "run_tiktok_research_evidence.py",
)
SANITIZED = ROOT / "tests" / "fixtures" / "tiktok_research_evidence" / "sanitized_creative_snapshot.json"


def _retirement_present() -> bool:
    if not LEGACY_CLIENT.is_file() or not LEGACY_CONNECTOR.is_file():
        return False
    client = LEGACY_CLIENT.read_text(encoding="utf-8")
    connector = LEGACY_CONNECTOR.read_text(encoding="utf-8")
    return (
        "offline compatibility shim" in client
        and "RAPIDAPI_KEY" not in client
        and "_fetch_live" not in connector
        and "TIKTOK_RESEARCH_TOKEN" not in connector
    )


def _route_gate_present() -> bool:
    if not ROUTE.is_file():
        return False
    text = ROUTE.read_text(encoding="utf-8")
    return "_live_action_denial" in text and "live_action_not_approved" in text


requires_retirement = pytest.mark.skipif(
    not _retirement_present(),
    reason="composition requires #459 legacy retirement",
)
requires_route_gate = pytest.mark.skipif(
    not _route_gate_present(),
    reason="composition requires #468 TikTok route approval gate",
)


def test_evidence_never_imports_legacy_or_ads_ingress():
    forbidden = {
        "connectors.tiktok_connector",
        "core.sensors.tiktok_client",
        "backend.integrations.tiktok_ads",
        "api.routes.tiktok",
    }
    for path in EVIDENCE_MODS:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        assert not (imported & forbidden), f"{path.name} imports {imported & forbidden}"


def test_research_tools_never_represented_as_commercially_available():
    report = build_tiktok_research_evidence(mode="not_configured")
    data = report.to_dict()
    assert data["capability_status"] in {"not_configured", "blocked_ineligible_commercial_use"}
    assert data["live_provider_calls"] is False
    assert data["network_calls"] is False
    assert data["execution_authorized"] is False
    assert data["authority"]["authenticated_observation"] is False
    assert data["authority"]["live_provider_calls"] is False
    for surface in research_tool_capabilities():
        assert surface.eligible_for_marketos_commercial_use is False
        assert surface.live_transport_implemented is False
        assert surface.status == "blocked_ineligible_commercial_use"
    for blocker in COMMERCIAL_INELIGIBILITY:
        assert blocker in data["blockers"]
    faq = next(item for item in official_citations() if "faq" in item["url"])
    assert faq["access_date"] == ACCESS_DATE


def test_fixture_and_fake_never_become_observed_or_live():
    fixture = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED)
    assert fixture.evidence_count >= 1
    assert fixture.live_provider_calls is False
    assert fixture.network_calls is False
    assert fixture.authority["authenticated_observation"] is False
    assert "fixture_or_fake_transport_not_authenticated_observation" in fixture.assumptions
    assert "research_tools_live_path_remains_blocked" in fixture.warnings

    fake = build_tiktok_research_evidence(
        mode="fake_transport",
        transport=FakeTikTokResearchTransport(
            status="ok",
            rows=(
                {
                    "candidate_id": "composition-widget",
                    "query": "composition widget",
                    "platform": "tiktok",
                    "hook": "offline only",
                    "view_count": 10,
                },
            ),
        ),
    )
    assert fake.capability_status == "fake_transport_ok"
    assert fake.live_provider_calls is False
    assert fake.authority["purchase_evidence"] is False
    assert fake.authority["supplier_proof"] is False


def test_live_request_states_fail_closed_and_empty():
    allow_live = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED, allow_live=True)
    assert allow_live.capability_status == "blocked_live_mode"
    assert allow_live.evidence_count == 0
    assert allow_live.attention_report is None

    live_bridge = bridge.fetch_research_evidence(
        "widget",
        context=SidecarContext(dry_run=False),
        mode="fixture_demo",
        fixture_path=SANITIZED,
    )
    assert live_bridge.status == "blocked_live_mode"
    assert live_bridge.evidence_count == 0
    assert live_bridge.report == {}
    assert live_bridge.commercial_eligible is False


def test_malformed_raw_secret_fail_closed():
    secret = ROOT / "tests" / "fixtures" / "tiktok_research_evidence" / "secret_like_rejected.json"
    raw = ROOT / "tests" / "fixtures" / "tiktok_research_evidence" / "raw_payload_rejected.json"
    secret_report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=secret)
    raw_report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=raw)
    assert secret_report.evidence_count == 0
    assert raw_report.evidence_count == 0
    assert any("secret" in item for item in secret_report.warnings)
    assert any("raw_payload" in item for item in raw_report.warnings)
    bad_mode = build_tiktok_research_evidence(mode="live_scrape")
    assert bad_mode.capability_status == "malformed_input"


@requires_retirement
def test_composed_legacy_ingress_stays_retired_and_unread(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "must-not-be-read")
    monkeypatch.setenv("TIKTOK_RESEARCH_TOKEN", "must-not-be-read")
    client = importlib.reload(importlib.import_module("core.sensors.tiktok_client"))
    connector = importlib.reload(importlib.import_module("connectors.tiktok_connector"))
    assert client.fetch_trending() == []
    assert connector.fetch_trending(limit=2)
    for path in (LEGACY_CLIENT, LEGACY_CONNECTOR):
        text = path.read_text(encoding="utf-8").lower()
        for snippet in ("rapidapi", "requests", "os.getenv", "os.environ", "_fetch_live", "open.tiktokapis.com"):
            assert snippet not in text, f"{path.name} still contains {snippet}"


@requires_retirement
def test_composed_evidence_does_not_reenable_retired_live_clients():
    # Evidence path remains independent of retired modules even after composition.
    report = build_tiktok_research_evidence(mode="fixture_demo", fixture_path=SANITIZED)
    blob = str(report.to_dict())
    assert "RAPIDAPI_KEY" not in blob
    assert "TIKTOK_RESEARCH_TOKEN" not in blob
    assert report.live_provider_calls is False
    assert "backend.adapters.tiktok_organic" in (ROOT / "core" / "signals.py").read_text(encoding="utf-8")


@requires_route_gate
def test_composed_route_denies_before_provider_execution():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes.tiktok import router
    from backend.integrations import tiktok_ads

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    calls: list[str] = []

    def boom(*_args, **_kwargs):
        calls.append("provider")
        raise AssertionError("provider must not run after denial")

    # Force live-mode flag; denial must return before launch_from_playbook.
    tiktok_ads._DRY_RUN = False
    original_launch = tiktok_ads.launch_from_playbook
    tiktok_ads.launch_from_playbook = boom  # type: ignore[method-assign]
    try:
        response = client.post("/tiktok/launch?product=composition-product&approved=true")
    finally:
        tiktok_ads.launch_from_playbook = original_launch  # type: ignore[method-assign]
        tiktok_ads._DRY_RUN = True

    assert response.status_code == 403
    body = response.json()
    assert body["status"] == "blocked"
    assert body["error"] == "live_action_not_approved"
    assert calls == []


@requires_route_gate
def test_composed_route_does_not_call_research_evidence_or_legacy():
    route_text = ROUTE.read_text(encoding="utf-8")
    assert "tiktok_research_evidence" not in route_text
    assert "tiktok_connector" not in route_text
    assert "tiktok_client" not in route_text
    assert "tiktok_organic" not in route_text
