"""Operator gates for the intelligence, creative-intelligence and commercial-intelligence POST routes.

These routes were mounted with no caller identity. Each now depends on one of three gates in
``backend/identity/operator_gates.py``. The requests below go through the production application object
(``backend.api.app``), and identity uses the production dependency chain: a fake verifier maps synthetic
tokens to principals, and memberships live in the SQLite-backed repository from ``tests/identity/conftest.py``.
Every engine, registry and file-writing entry point that a handler calls is replaced by a recorder, so a
refused request must leave every recorder empty. Nothing here reads real credentials, a real database, the
state directory, or the network.
"""
from __future__ import annotations

import warnings

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.operator_gates import (
    commercial_intelligence_run_gate,
    creative_intelligence_run_gate,
    intelligence_run_gate,
)
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import (
    CLIENT_VIEWER,
    COMMERCIAL_INTELLIGENCE_RUN,
    CREATIVE_INTELLIGENCE_RUN,
    INTELLIGENCE_RUN,
    INTERNAL_OPERATOR,
    role_grants,
)

from .conftest import ALICE, ISSUER, OWNER_ALICE

VIEWER = VerifiedPrincipal(ISSUER, "user_viewer")
TOKENS = {"tok-operator": ALICE, "tok-viewer": VIEWER}
OPERATOR_HEADERS = {"Authorization": "Bearer tok-operator"}
PREFIXES = ("/api/intelligence", "/api/creative-intelligence", "/api/commercial-intelligence")

# Every POST route under the three prefixes, with the gate it must depend on. A new POST route in these
# prefixes fails ``test_every_post_route_under_the_intelligence_prefixes_depends_on_its_gate`` until it is listed.
EXPECTED_GATES = {
    "/api/intelligence/cycle": intelligence_run_gate,
    "/api/intelligence/knowledge-graph/build": intelligence_run_gate,
    "/api/intelligence/strategic-priorities/build": intelligence_run_gate,
    "/api/intelligence/research-campaigns/build": intelligence_run_gate,
    "/api/intelligence/executive-briefs/build": intelligence_run_gate,
    "/api/creative-intelligence/cycle": creative_intelligence_run_gate,
    "/api/creative-intelligence/buyer-psychology": creative_intelligence_run_gate,
    "/api/creative-intelligence/angles/generate": creative_intelligence_run_gate,
    "/api/creative-intelligence/hooks/generate": creative_intelligence_run_gate,
    "/api/creative-intelligence/claims/validate": creative_intelligence_run_gate,
    "/api/commercial-intelligence/features/extract": commercial_intelligence_run_gate,
    "/api/commercial-intelligence/market/analyze": commercial_intelligence_run_gate,
    "/api/commercial-intelligence/product/analyze": commercial_intelligence_run_gate,
    "/api/commercial-intelligence/cycle": commercial_intelligence_run_gate,
}

GATED_ROUTES = [
    pytest.param("/api/intelligence/cycle", {"workspace_id": "ws-1"}, id="intelligence-cycle"),
    pytest.param("/api/intelligence/knowledge-graph/build", {"workspace_id": "ws-1"}, id="intelligence-graph-build"),
    pytest.param("/api/intelligence/strategic-priorities/build", {"workspace_id": "ws-1"}, id="intelligence-priorities-build"),
    pytest.param("/api/intelligence/research-campaigns/build", {"workspace_id": "ws-1"}, id="intelligence-campaigns-build"),
    pytest.param("/api/intelligence/executive-briefs/build", {"workspace_id": "ws-1"}, id="intelligence-briefs-build"),
    pytest.param("/api/creative-intelligence/cycle", {"workspace_id": "ws-1", "product_name": "Widget"}, id="creative-cycle"),
    pytest.param("/api/creative-intelligence/buyer-psychology", {"workspace_id": "ws-1", "product_name": "Widget"}, id="creative-buyer-psychology"),
    pytest.param("/api/creative-intelligence/angles/generate", {"workspace_id": "ws-1", "product_name": "Widget"}, id="creative-angles-generate"),
    pytest.param("/api/creative-intelligence/hooks/generate", {"angle_ids": ["angle-1"]}, id="creative-hooks-generate"),
    pytest.param("/api/creative-intelligence/claims/validate", {"claim": "Lowers cost"}, id="creative-claims-validate"),
    pytest.param("/api/commercial-intelligence/features/extract", {"workspace_id": "ws-1"}, id="commercial-features-extract"),
    pytest.param("/api/commercial-intelligence/market/analyze", {"workspace_id": "ws-1", "category_name": "Kitchen"}, id="commercial-market-analyze"),
    pytest.param("/api/commercial-intelligence/product/analyze", {"workspace_id": "ws-1", "product_name": "Widget"}, id="commercial-product-analyze"),
    pytest.param("/api/commercial-intelligence/cycle", {"workspace_id": "ws-1"}, id="commercial-cycle"),
]

# (wiring, headers, expected status, expected code). Wiring says which identity providers the app has:
# "wired" both, "no_verifier" only the repository, "no_repository" only the verifier.
REFUSALS = [
    pytest.param("wired", {}, 401, "missing_credentials", id="anonymous"),
    pytest.param("wired", {"Authorization": "Bearer tok-forged"}, 401, "invalid_credentials", id="forged-token"),
    pytest.param("wired", {"Authorization": "Bearer tok-viewer"}, 403, "role_not_authorized", id="client-viewer"),
    pytest.param("no_verifier", OPERATOR_HEADERS, 503, "identity_provider_unavailable", id="unconfigured-verifier"),
    pytest.param("no_repository", OPERATOR_HEADERS, 503, "storage_unavailable", id="unconfigured-repository"),
]

CLAIM_RESULT = {"status": "safe", "safe_text": "Lowers cost", "blocked_reasons": [], "limitations": []}

# Authorized operator: the response body and the exact ordered list of effects the handler performs.
AUTHORIZED = [
    pytest.param(
        "/api/intelligence/cycle", {"workspace_id": "ws-1"},
        {"status": "completed", "warnings": []},
        ["intelligence.cycle"],
        id="intelligence-cycle",
    ),
    pytest.param(
        "/api/intelligence/knowledge-graph/build", {"workspace_id": "ws-1"},
        {"snapshot": {"snapshot_id": "graph-1"}, "status": "completed"},
        ["intelligence.knowledge_graph"],
        id="intelligence-graph-build",
    ),
    pytest.param(
        "/api/intelligence/strategic-priorities/build", {"workspace_id": "ws-1"},
        {"plan": {"plan_id": "plan-1"}},
        ["intelligence.strategic_priorities", "intelligence_registry.open", "intelligence_registry.register_priority_plan"],
        id="intelligence-priorities-build",
    ),
    pytest.param(
        "/api/intelligence/research-campaigns/build", {"workspace_id": "ws-1"},
        {"plan": {"plan_id": "campaign-1"}},
        ["intelligence.research_campaigns", "intelligence_registry.open", "intelligence_registry.register_campaign_plan"],
        id="intelligence-campaigns-build",
    ),
    pytest.param(
        "/api/intelligence/executive-briefs/build", {"workspace_id": "ws-1"},
        {"brief": {"brief_id": "brief-1"}, "status": "completed"},
        ["intelligence.executive_brief"],
        id="intelligence-briefs-build",
    ),
    pytest.param(
        "/api/creative-intelligence/cycle", {"workspace_id": "ws-1", "product_name": "Widget"},
        {"status": "completed"},
        ["creative.cycle"],
        id="creative-cycle",
    ),
    pytest.param(
        "/api/creative-intelligence/buyer-psychology", {"workspace_id": "ws-1", "product_name": "Widget"},
        {"status": "completed", "buyer_psychology_map": {"map_id": "map-1"}},
        ["creative.buyer_psychology"],
        id="creative-buyer-psychology",
    ),
    pytest.param(
        "/api/creative-intelligence/angles/generate", {"workspace_id": "ws-1", "product_name": "Widget"},
        {"status": "completed", "angles": [{"angle_id": "angle-1"}]},
        ["creative.angles"],
        id="creative-angles-generate",
    ),
    pytest.param(
        "/api/creative-intelligence/hooks/generate", {"angle_ids": ["angle-1"]},
        {"status": "completed", "hooks": [{"hook_id": "hook-1"}]},
        ["creative_registry.open", "creative.hooks"],
        id="creative-hooks-generate",
    ),
    pytest.param(
        "/api/creative-intelligence/claims/validate", {"claim": "Lowers cost"},
        CLAIM_RESULT,
        ["creative.sanitize_claim"],
        id="creative-claims-validate",
    ),
    pytest.param(
        "/api/commercial-intelligence/features/extract", {"workspace_id": "ws-1"},
        {"status": "completed", "feature_set": {"feature_set_id": "fs-1"}},
        ["commercial.extract_features"],
        id="commercial-features-extract",
    ),
    pytest.param(
        "/api/commercial-intelligence/market/analyze", {"workspace_id": "ws-1", "category_name": "Kitchen"},
        {"status": "completed", "market_report": {"report_id": "market-1"}},
        ["commercial.market_analyze"],
        id="commercial-market-analyze",
    ),
    pytest.param(
        "/api/commercial-intelligence/product/analyze", {"workspace_id": "ws-1", "product_name": "Widget"},
        {"status": "completed", "product_report": {"report_id": "product-1"}},
        ["commercial.product_analyze"],
        id="commercial-product-analyze",
    ),
    pytest.param(
        "/api/commercial-intelligence/cycle", {"workspace_id": "ws-1"},
        {"status": "completed", "warnings": []},
        ["commercial.cycle"],
        id="commercial-cycle",
    ),
]


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


class Effects:
    """Records each side effect and outbound call that a gated handler would make."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))

    def names(self) -> list[str]:
        return [name for name, _args, _kwargs in self.calls]


class _Report:
    def __init__(self, body: dict) -> None:
        self._body = body

    def to_dict(self) -> dict:
        return dict(self._body)


@pytest.fixture
def store(repo):
    repo.create_workspace(OWNER_ALICE, "internal", "Owner Workspace")
    repo.add_member(OWNER_ALICE, ALICE.issuer, ALICE.subject, INTERNAL_OPERATOR)
    # A client_viewer in the internal workspace: the membership exists, and the role must still refuse.
    repo.add_member(OWNER_ALICE, VIEWER.issuer, VIEWER.subject, CLIENT_VIEWER)
    return repo


@pytest.fixture
def api(monkeypatch):
    import backend.api as module

    # Each test wires its own identity providers; none may leak in from another module.
    monkeypatch.delitem(module.app.dependency_overrides, get_token_verifier, raising=False)
    monkeypatch.delitem(module.app.dependency_overrides, get_workspace_repository, raising=False)
    return module


@pytest.fixture
def effects(api, monkeypatch) -> Effects:
    import api.routes.commercial_intelligence as commercial_routes
    import api.routes.creative_intelligence as creative_routes
    import api.routes.intelligence as intelligence_routes

    rec = Effects()

    def stub(name: str, result):
        def run(*args, **kwargs):
            rec.record(name, *args, **kwargs)
            return result

        return run

    class _Registry:
        def __init__(self, domain: str) -> None:
            self._domain = domain

        def register_priority_plan(self, plan) -> None:
            rec.record(f"{self._domain}.register_priority_plan", plan)

        def register_campaign_plan(self, plan) -> None:
            rec.record(f"{self._domain}.register_campaign_plan", plan)

        def get_angle(self, angle_id: str):
            return _Report({"angle_id": angle_id})

    def registry(domain: str):
        def open_registry():
            rec.record(f"{domain}.open")
            return _Registry(domain)

        return open_registry

    # Executive intelligence (api/routes/intelligence.py).
    monkeypatch.setattr(intelligence_routes, "run_executive_intelligence_cycle", stub("intelligence.cycle", {"status": "completed", "warnings": []}))
    monkeypatch.setattr(intelligence_routes, "build_knowledge_graph_snapshot", stub("intelligence.knowledge_graph", {"snapshot": {"snapshot_id": "graph-1"}, "status": "completed"}))
    monkeypatch.setattr(intelligence_routes, "build_strategic_priority_plan", stub("intelligence.strategic_priorities", _Report({"plan_id": "plan-1"})))
    monkeypatch.setattr(intelligence_routes, "build_research_campaign_plan", stub("intelligence.research_campaigns", _Report({"plan_id": "campaign-1"})))
    monkeypatch.setattr(intelligence_routes, "build_executive_brief", stub("intelligence.executive_brief", {"brief": {"brief_id": "brief-1"}, "status": "completed"}))
    monkeypatch.setattr(intelligence_routes, "get_intelligence_registry", registry("intelligence_registry"))

    # Creative intelligence (api/routes/creative_intelligence.py).
    monkeypatch.setattr(creative_routes, "run_creative_intelligence_cycle", stub("creative.cycle", {"status": "completed"}))
    monkeypatch.setattr(creative_routes, "build_buyer_psychology_map", stub("creative.buyer_psychology", _Report({"map_id": "map-1"})))
    monkeypatch.setattr(creative_routes, "generate_creative_angles", stub("creative.angles", [_Report({"angle_id": "angle-1"})]))
    monkeypatch.setattr(creative_routes, "generate_hooks_for_angles", stub("creative.hooks", [_Report({"hook_id": "hook-1"})]))
    monkeypatch.setattr(creative_routes, "sanitize_creative_claim", stub("creative.sanitize_claim", CLAIM_RESULT))
    monkeypatch.setattr(creative_routes, "get_creative_registry", registry("creative_registry"))

    # Commercial intelligence (api/routes/commercial_intelligence.py).
    monkeypatch.setattr(commercial_routes, "extract_evidence_features", stub("commercial.extract_features", _Report({"feature_set_id": "fs-1"})))
    monkeypatch.setattr(commercial_routes, "analyze_market_category", stub("commercial.market_analyze", _Report({"report_id": "market-1"})))
    monkeypatch.setattr(commercial_routes, "analyze_product_viability", stub("commercial.product_analyze", _Report({"report_id": "product-1"})))
    monkeypatch.setattr(commercial_routes, "run_commercial_intelligence_cycle", stub("commercial.cycle", {"status": "completed", "warnings": []}))
    return rec


def _wire(api, monkeypatch, store, wiring: str) -> None:
    if wiring in ("wired", "no_repository"):
        monkeypatch.setitem(api.app.dependency_overrides, get_token_verifier, lambda: FakeVerifier())
    if wiring in ("wired", "no_verifier"):
        monkeypatch.setitem(api.app.dependency_overrides, get_workspace_repository, lambda: store)


def _dependency_calls(route: APIRoute) -> set:
    return {dependency.call for dependency in route.dependant.dependencies}


@pytest.mark.parametrize("path, body", GATED_ROUTES)
@pytest.mark.parametrize("wiring, headers, status, code", REFUSALS)
def test_refused_identity_runs_no_handler_and_changes_nothing(api, store, effects, monkeypatch, path, body, wiring, headers, status, code):
    _wire(api, monkeypatch, store, wiring)

    response = TestClient(api.app).post(path, json=body, headers=headers)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert effects.calls == []


@pytest.mark.parametrize("path, body, expected_body, expected_effects", AUTHORIZED)
def test_operator_gets_the_unchanged_response_and_the_expected_effects(api, store, effects, monkeypatch, path, body, expected_body, expected_effects):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).post(path, json=body, headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    assert response.json() == expected_body
    assert effects.names() == expected_effects


def test_the_operator_payload_reaches_the_handler_unchanged(api, store, effects, monkeypatch):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).post("/api/commercial-intelligence/cycle", json={"workspace_id": "ws-7", "category_name": "Kitchen"}, headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    _name, args, _kwargs = effects.calls[0]
    assert args[0] == "ws-7" and args[1] == "Kitchen"


def test_every_post_route_under_the_intelligence_prefixes_depends_on_its_gate(api):
    """Structural guard: a new or ungated POST in these prefixes fails here, not only in a request."""
    import api.routes.commercial_intelligence as commercial_routes
    import api.routes.creative_intelligence as creative_routes
    import api.routes.intelligence as intelligence_routes

    seen = {}
    for router in (intelligence_routes.router, creative_routes.router, commercial_routes.router):
        for route in router.routes:
            if isinstance(route, APIRoute) and "POST" in route.methods:
                seen[route.path] = _dependency_calls(route)

    assert set(seen) == set(EXPECTED_GATES)
    for path, gate in EXPECTED_GATES.items():
        assert gate in seen[path], f"POST {path} does not depend on its operator gate"

    # The production app must publish the same POST operations, so the routers are mounted and nothing is orphaned.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # unrelated routes in the app trigger duplicate-operation-id warnings
        paths = api.app.openapi()["paths"]
    published = {
        path for path, operations in paths.items() if path.startswith(PREFIXES) for method in operations if method.upper() == "POST"
    }
    assert published == set(EXPECTED_GATES)


def test_intelligence_run_permissions_are_granted_to_internal_operator_only():
    assert INTELLIGENCE_RUN == "intelligence:run"
    assert CREATIVE_INTELLIGENCE_RUN == "creative_intelligence:run"
    assert COMMERCIAL_INTELLIGENCE_RUN == "commercial_intelligence:run"
    for permission in (INTELLIGENCE_RUN, CREATIVE_INTELLIGENCE_RUN, COMMERCIAL_INTELLIGENCE_RUN):
        assert role_grants(INTERNAL_OPERATOR, permission)
        assert not role_grants(CLIENT_VIEWER, permission)
        assert not role_grants(None, permission)
        assert not role_grants("unknown_role", permission)
