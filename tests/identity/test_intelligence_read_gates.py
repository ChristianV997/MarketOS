"""Read routes of the intelligence, creative-intelligence and commercial-intelligence APIs.

Every GET route under these prefixes, and the read-only POST /api/commercial-intelligence/features/extract, is gated by
the domain run permission and bound to the verified workspace. A list reads only that workspace. A by-ID read answers a
foreign record exactly as it answers an unknown one. The requests go through the production application object, and
identity uses the production dependency chain: a fake verifier maps synthetic tokens to principals, and memberships live
in the SQLite-backed repository from ``tests/identity/conftest.py``.

Each registry is a fake that mirrors the real semantics: list methods filter by workspace only when one is given, and
by-ID getters do not filter at all. Every call is recorded, so a refused read must leave the recorder empty. All records
are synthetic. Nothing here reads real credentials, a real database, the state directory, or the network.
"""
from __future__ import annotations

from types import SimpleNamespace

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
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR

from .conftest import ALICE, ISSUER, OWNER_ALICE, OWNER_BOB

VIEWER = VerifiedPrincipal(ISSUER, "user_viewer")
TOKENS = {"tok-operator": ALICE, "tok-viewer": VIEWER}
OPERATOR_HEADERS = {"Authorization": "Bearer tok-operator"}

# (wiring, headers, expected status, expected code). Wiring says which identity providers the app has.
REFUSALS = [
    pytest.param("wired", {}, 401, "missing_credentials", id="anonymous"),
    pytest.param("wired", {"Authorization": "Bearer tok-forged"}, 401, "invalid_credentials", id="forged-token"),
    pytest.param("wired", {"Authorization": "Bearer tok-viewer"}, 403, "role_not_authorized", id="client-viewer"),
    pytest.param("no_verifier", OPERATOR_HEADERS, 503, "identity_provider_unavailable", id="unconfigured-verifier"),
    pytest.param("no_repository", OPERATOR_HEADERS, 503, "storage_unavailable", id="unconfigured-repository"),
]

# Every list route: path, body key, id key, the verified workspace's record id, and a foreign record id.
LIST_ROUTES = [
    pytest.param("/api/intelligence/knowledge-graph/snapshots", "snapshots", "snapshot_id", "snap-alice", "snap-bob", id="graph-snapshots"),
    pytest.param("/api/intelligence/knowledge-graph/nodes", "nodes", "node_id", ("node-alice", "node-alice-2", "node-alice-3"), "node-bob", id="graph-nodes"),
    pytest.param("/api/intelligence/strategic-priorities", "plans", "plan_id", "plan-alice", "plan-bob", id="priorities"),
    pytest.param("/api/intelligence/research-campaigns", "plans", "plan_id", "campaign-alice", "campaign-bob", id="campaigns"),
    pytest.param("/api/intelligence/executive-briefs", "briefs", "brief_id", "brief-alice", "brief-bob", id="briefs"),
    pytest.param("/api/creative-intelligence/reports", "reports", "report_id", "report-alice", "report-bob", id="creative-reports"),
    pytest.param("/api/creative-intelligence/angles", "angles", "angle_id", "angle-alice", "angle-bob", id="creative-angles"),
    pytest.param("/api/creative-intelligence/hooks", "hooks", "hook_id", "hook-alice", "hook-bob", id="creative-hooks"),
    pytest.param("/api/creative-intelligence/ugc-briefs", "ugc_briefs", "brief_id", "ugc-alice", "ugc-bob", id="creative-ugc-briefs"),
    pytest.param("/api/creative-intelligence/storyboards", "storyboards", "storyboard_id", "storyboard-alice", "storyboard-bob", id="creative-storyboards"),
    pytest.param("/api/creative-intelligence/claim-maps", "claim_maps", "claim_map_id", "claim-map-alice", "claim-map-bob", id="creative-claim-maps"),
    pytest.param("/api/creative-intelligence/test-matrices", "test_matrices", "matrix_id", "matrix-alice", "matrix-bob", id="creative-test-matrices"),
    pytest.param("/api/commercial-intelligence/features", "feature_sets", "feature_set_id", "fs-alice", "fs-bob", id="commercial-features"),
    pytest.param("/api/commercial-intelligence/market/reports", "market_reports", "report_id", "market-alice", "market-bob", id="commercial-market-reports"),
    pytest.param("/api/commercial-intelligence/product/reports", "product_reports", "report_id", "product-alice", "product-bob", id="commercial-product-reports"),
]

# Every by-ID read except neighbors (tested separately): template, verified record id, foreign record id.
DETAIL_ROUTES = [
    pytest.param("/api/intelligence/knowledge-graph/snapshots/{id}", "snap-alice", "snap-bob", id="graph-snapshot"),
    pytest.param("/api/intelligence/knowledge-graph/nodes/{id}", "node-alice", "node-bob", id="graph-node"),
    pytest.param("/api/intelligence/strategic-priorities/{id}", "plan-alice", "plan-bob", id="priority"),
    pytest.param("/api/intelligence/research-campaigns/{id}", "campaign-alice", "campaign-bob", id="campaign"),
    pytest.param("/api/intelligence/executive-briefs/{id}", "brief-alice", "brief-bob", id="brief"),
    pytest.param("/api/intelligence/executive-briefs/{id}/markdown", "brief-alice", "brief-bob", id="brief-markdown"),
    pytest.param("/api/intelligence/executive-briefs/{id}/html", "brief-alice", "brief-bob", id="brief-html"),
    pytest.param("/api/creative-intelligence/reports/{id}", "report-alice", "report-bob", id="creative-report"),
    pytest.param("/api/commercial-intelligence/features/{id}", "fs-alice", "fs-bob", id="commercial-feature-set"),
    pytest.param("/api/commercial-intelligence/market/reports/{id}", "market-alice", "market-bob", id="commercial-market-report"),
    pytest.param("/api/commercial-intelligence/product/reports/{id}", "product-alice", "product-bob", id="commercial-product-report"),
]

GATE_BY_PREFIX = {
    "/api/intelligence": intelligence_run_gate,
    "/api/creative-intelligence": creative_intelligence_run_gate,
    "/api/commercial-intelligence": commercial_intelligence_run_gate,
}
EXTRACT_PATH = "/api/commercial-intelligence/features/extract"


class Reads:
    """Records every registry or engine call. A refused request must leave it empty."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def record(self, name: str, *args, **kwargs) -> None:
        self.calls.append((name, args, kwargs))


class Record:
    """A synthetic registry record. Its title carries its own id, so a leaked record is visible in any response."""

    def __init__(self, id_field: str, record_id: str, workspace_id: str, **fields) -> None:
        setattr(self, id_field, record_id)
        self.workspace_id = workspace_id
        self.title = f"title for {record_id}"
        for key, value in fields.items():
            setattr(self, key, value)

    def to_dict(self) -> dict:
        return dict(vars(self))


class BriefRecord(Record):
    def to_markdown(self) -> str:
        return f"# {self.title}"

    def to_html_fragment(self) -> str:
        return f"<h1>{self.title}</h1>"


class _Report:
    def __init__(self, body: dict) -> None:
        self._body = body

    def to_dict(self) -> dict:
        return dict(self._body)


def _select(items: dict, workspace_id, **criteria) -> list:
    """Mirrors the real list methods: the workspace filter applies only when a workspace is given."""
    return [
        item
        for item in items.values()
        if (workspace_id is None or item.workspace_id == workspace_id)
        and all(value is None or getattr(item, key, None) == value for key, value in criteria.items())
    ]


class KnowledgeFake:
    def __init__(self, reads: Reads, nodes: dict, snapshots: dict, links: list) -> None:
        self.reads, self.nodes, self.snapshots, self.links = reads, nodes, snapshots, links

    def list_snapshots(self, workspace_id=None, limit=50):
        self.reads.record("knowledge.list_snapshots", workspace_id, limit)
        return _select(self.snapshots, workspace_id)[:limit]

    def get_snapshot(self, snapshot_id):
        self.reads.record("knowledge.get_snapshot", snapshot_id)
        return self.snapshots.get(snapshot_id)

    def list_nodes(self, workspace_id=None, node_type=None, status=None, limit=200):
        self.reads.record("knowledge.list_nodes", workspace_id, node_type, status, limit=limit)
        return _select(self.nodes, workspace_id, node_type=node_type, status=status)[:limit]

    def get_node(self, node_id):
        self.reads.record("knowledge.get_node", node_id)
        return self.nodes.get(node_id)

    def neighbors(self, node_id, relation_type=None, direction="both", limit=100):
        self.reads.record("knowledge.neighbors", node_id, relation_type, direction, limit)
        # Mirrors the real registry: neighbours in link order, the limit applied before the existence check, capped at 500.
        ids: list[str] = []
        for a, b in self.links:
            other = b if a == node_id else a if b == node_id else None
            if other is not None and other not in ids:
                ids.append(other)
        return [self.nodes[i] for i in ids[: max(0, min(int(limit), 500))] if i in self.nodes]


class IntelligenceFake:
    def __init__(self, reads: Reads, plans: dict, campaigns: dict, briefs: dict) -> None:
        self.reads, self.plans, self.campaigns, self.briefs = reads, plans, campaigns, briefs

    def list_priority_plans(self, workspace_id=None, limit=50):
        self.reads.record("intelligence.list_priority_plans", workspace_id, limit)
        return _select(self.plans, workspace_id)[:limit]

    def get_priority_plan(self, plan_id):
        self.reads.record("intelligence.get_priority_plan", plan_id)
        return self.plans.get(plan_id)

    def list_campaign_plans(self, workspace_id=None, limit=50):
        self.reads.record("intelligence.list_campaign_plans", workspace_id, limit)
        return _select(self.campaigns, workspace_id)[:limit]

    def get_campaign_plan(self, plan_id):
        self.reads.record("intelligence.get_campaign_plan", plan_id)
        return self.campaigns.get(plan_id)

    def list_executive_briefs(self, workspace_id=None, limit=50):
        self.reads.record("intelligence.list_executive_briefs", workspace_id, limit)
        return _select(self.briefs, workspace_id)[:limit]

    def get_executive_brief(self, brief_id):
        self.reads.record("intelligence.get_executive_brief", brief_id)
        return self.briefs.get(brief_id)


class CreativeFake:
    def __init__(self, reads: Reads, items: dict) -> None:
        self.reads, self.items = reads, items

    def get_report(self, report_id):
        self.reads.record("creative.get_report", report_id)
        return self.items["reports"].get(report_id)


def _creative_lister(kind: str):
    def list_items(self, workspace_id=None, opportunity_id=None, product_name=None, category_name=None, angle_id=None, limit=50):
        self.reads.record(f"creative.list_{kind}", workspace_id, opportunity_id, product_name, category_name, angle_id, limit)
        return _select(self.items[kind], workspace_id, opportunity_id=opportunity_id, product_name=product_name, category_name=category_name, angle_id=angle_id)[:limit]

    return list_items


for _kind in ("reports", "angles", "hooks", "ugc_briefs", "storyboards", "claim_maps", "test_matrices"):
    setattr(CreativeFake, f"list_{_kind}", _creative_lister(_kind))


class CommercialFake:
    def __init__(self, reads: Reads, feature_sets: dict, market_reports: dict, product_reports: dict) -> None:
        self.reads = reads
        self.feature_sets, self.market_reports, self.product_reports = feature_sets, market_reports, product_reports

    def list_feature_sets(self, workspace_id=None, limit=50):
        self.reads.record("commercial.list_feature_sets", workspace_id, limit)
        return _select(self.feature_sets, workspace_id)[:limit]

    def get_feature_set(self, feature_set_id):
        self.reads.record("commercial.get_feature_set", feature_set_id)
        return self.feature_sets.get(feature_set_id)

    def list_market_reports(self, workspace_id=None, category_name=None, limit=50):
        self.reads.record("commercial.list_market_reports", workspace_id, category_name, limit)
        return _select(self.market_reports, workspace_id, category_name=category_name)[:limit]

    def get_market_report(self, report_id):
        self.reads.record("commercial.get_market_report", report_id)
        return self.market_reports.get(report_id)

    def list_product_reports(self, workspace_id=None, product_name=None, category_name=None, opportunity_id=None, limit=50):
        self.reads.record("commercial.list_product_reports", workspace_id, product_name, category_name, opportunity_id, limit)
        return _select(self.product_reports, workspace_id, product_name=product_name, category_name=category_name, opportunity_id=opportunity_id)[:limit]

    def get_product_report(self, report_id):
        self.reads.record("commercial.get_product_report", report_id)
        return self.product_reports.get(report_id)


class _Opportunities:
    def __init__(self, reads: Reads) -> None:
        self.reads = reads

    def get_opportunity(self, item_id):
        self.reads.record("opportunities.get", item_id)
        owner = {"opp-alice": OWNER_ALICE, "opp-bob": OWNER_BOB}.get(item_id)
        return None if owner is None else SimpleNamespace(workspace_id=owner)


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


def _seed():
    """Synthetic records. Each kind has one record in the operator's workspace and one in another workspace."""
    nodes = {
        "node-alice": Record("node_id", "node-alice", OWNER_ALICE, node_type="opportunity", status="active"),
        "node-alice-2": Record("node_id", "node-alice-2", OWNER_ALICE, node_type="product", status="active"),
        "node-alice-3": Record("node_id", "node-alice-3", OWNER_ALICE, node_type="product", status="active"),
        "node-bob": Record("node_id", "node-bob", OWNER_BOB, node_type="opportunity", status="active"),
    }
    snapshots = {
        "snap-alice": Record("snapshot_id", "snap-alice", OWNER_ALICE),
        "snap-bob": Record("snapshot_id", "snap-bob", OWNER_BOB),
    }
    # The second link is synthetic and crosses workspaces, so the neighbours filter is exercised.
    links = [("node-alice", "node-alice-2"), ("node-alice", "node-bob"), ("node-alice", "node-alice-3")]
    plans = {"plan-alice": Record("plan_id", "plan-alice", OWNER_ALICE), "plan-bob": Record("plan_id", "plan-bob", OWNER_BOB)}
    campaigns = {"campaign-alice": Record("plan_id", "campaign-alice", OWNER_ALICE), "campaign-bob": Record("plan_id", "campaign-bob", OWNER_BOB)}
    briefs = {
        "brief-alice": BriefRecord("brief_id", "brief-alice", OWNER_ALICE),
        "brief-bob": BriefRecord("brief_id", "brief-bob", OWNER_BOB),
    }
    creative = {
        "reports": {
            "report-alice": Record("report_id", "report-alice", OWNER_ALICE, opportunity_id="opp-alice", product_name="Widget", category_name="Kitchen"),
            "report-bob": Record("report_id", "report-bob", OWNER_BOB, opportunity_id="opp-bob", product_name="Widget", category_name="Kitchen"),
        },
        "angles": {
            "angle-alice": Record("angle_id", "angle-alice", OWNER_ALICE, opportunity_id="opp-alice", product_name="Widget", category_name="Kitchen"),
            "angle-bob": Record("angle_id", "angle-bob", OWNER_BOB, opportunity_id="opp-bob", product_name="Widget", category_name="Kitchen"),
        },
        "hooks": {
            "hook-alice": Record("hook_id", "hook-alice", OWNER_ALICE, angle_id="angle-alice"),
            "hook-bob": Record("hook_id", "hook-bob", OWNER_BOB, angle_id="angle-bob"),
        },
        "ugc_briefs": {
            "ugc-alice": Record("brief_id", "ugc-alice", OWNER_ALICE, opportunity_id="opp-alice"),
            "ugc-bob": Record("brief_id", "ugc-bob", OWNER_BOB, opportunity_id="opp-bob"),
        },
        "storyboards": {
            "storyboard-alice": Record("storyboard_id", "storyboard-alice", OWNER_ALICE, opportunity_id="opp-alice"),
            "storyboard-bob": Record("storyboard_id", "storyboard-bob", OWNER_BOB, opportunity_id="opp-bob"),
        },
        "claim_maps": {
            "claim-map-alice": Record("claim_map_id", "claim-map-alice", OWNER_ALICE, opportunity_id="opp-alice"),
            "claim-map-bob": Record("claim_map_id", "claim-map-bob", OWNER_BOB, opportunity_id="opp-bob"),
        },
        "test_matrices": {
            "matrix-alice": Record("matrix_id", "matrix-alice", OWNER_ALICE, opportunity_id="opp-alice"),
            "matrix-bob": Record("matrix_id", "matrix-bob", OWNER_BOB, opportunity_id="opp-bob"),
        },
    }
    commercial = {
        "feature_sets": {
            "fs-alice": Record("feature_set_id", "fs-alice", OWNER_ALICE, category_name="Kitchen"),
            "fs-bob": Record("feature_set_id", "fs-bob", OWNER_BOB, category_name="Kitchen"),
        },
        "market_reports": {
            "market-alice": Record("report_id", "market-alice", OWNER_ALICE, category_name="Kitchen"),
            "market-bob": Record("report_id", "market-bob", OWNER_BOB, category_name="Kitchen"),
        },
        "product_reports": {
            "product-alice": Record("report_id", "product-alice", OWNER_ALICE, product_name="Widget", category_name="Kitchen", opportunity_id="opp-alice"),
            "product-bob": Record("report_id", "product-bob", OWNER_BOB, product_name="Widget", category_name="Kitchen", opportunity_id="opp-bob"),
        },
    }
    return nodes, snapshots, links, plans, campaigns, briefs, creative, commercial


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
def reads(api, monkeypatch) -> Reads:
    import api.routes.commercial_intelligence as commercial_routes
    import api.routes.creative_intelligence as creative_routes
    import api.routes.intelligence as intelligence_routes
    import backend.discovery.opportunity_registry as opportunity_module

    rec = Reads()
    nodes, snapshots, links, plans, campaigns, briefs, creative, commercial = _seed()

    def extract(*args, **kwargs):
        rec.record("commercial.extract_features", *args, **kwargs)
        return _Report({"feature_set_id": "fs-extracted"})

    monkeypatch.setattr(intelligence_routes, "get_knowledge_registry", lambda: KnowledgeFake(rec, nodes, snapshots, links))
    monkeypatch.setattr(intelligence_routes, "get_intelligence_registry", lambda: IntelligenceFake(rec, plans, campaigns, briefs))
    monkeypatch.setattr(creative_routes, "get_creative_registry", lambda: CreativeFake(rec, creative))
    monkeypatch.setattr(commercial_routes, "get_commercial_intelligence_registry", lambda: CommercialFake(rec, *commercial.values()))
    monkeypatch.setattr(commercial_routes, "extract_evidence_features", extract)
    monkeypatch.setattr(opportunity_module, "get_opportunity_registry", lambda: _Opportunities(rec))
    return rec


def _wire(api, monkeypatch, store, wiring: str) -> None:
    if wiring in ("wired", "no_repository"):
        monkeypatch.setitem(api.app.dependency_overrides, get_token_verifier, lambda: FakeVerifier())
    if wiring in ("wired", "no_verifier"):
        monkeypatch.setitem(api.app.dependency_overrides, get_workspace_repository, lambda: store)


def _dependency_calls(route: APIRoute) -> set:
    return {dependency.call for dependency in route.dependant.dependencies}


def _calls(reads: Reads, name: str) -> list[tuple]:
    return [args for call_name, args, _kwargs in reads.calls if call_name == name]


# Every read route, plus the read-only extract, with a path that names a verified-workspace record.
REFUSAL_ROUTES = (
    [pytest.param("GET", path, id=f"list-{path}") for path, *_rest in [p.values for p in LIST_ROUTES]]
    + [pytest.param("GET", template.format(id=owned), id=f"detail-{template}") for template, owned, _foreign in [p.values for p in DETAIL_ROUTES]]
    + [pytest.param("GET", "/api/intelligence/knowledge-graph/nodes/node-alice/neighbors", id="graph-neighbors")]
    + [pytest.param("POST", EXTRACT_PATH, id="features-extract")]
)


@pytest.mark.parametrize("method, path", REFUSAL_ROUTES)
@pytest.mark.parametrize("wiring, headers, status, code", REFUSALS)
def test_refused_identity_reads_nothing(api, store, reads, monkeypatch, method, path, wiring, headers, status, code):
    _wire(api, monkeypatch, store, wiring)

    response = TestClient(api.app).request(method, path, json={} if method == "POST" else None, headers=headers)

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert reads.calls == []


@pytest.mark.parametrize("path, body_key, id_key, owned_id, foreign_id", LIST_ROUTES)
@pytest.mark.parametrize("selector", [None, OWNER_ALICE], ids=["absent", "verified"])
def test_a_list_returns_only_the_verified_workspace(api, store, reads, monkeypatch, path, body_key, id_key, owned_id, foreign_id, selector):
    _wire(api, monkeypatch, store, "wired")
    url = path if selector is None else f"{path}?workspace_id={selector}"

    response = TestClient(api.app).get(url, headers=OPERATOR_HEADERS)

    expected = list(owned_id) if isinstance(owned_id, tuple) else [owned_id]
    assert response.status_code == 200
    assert [item[id_key] for item in response.json()[body_key]] == expected
    assert f"title for {foreign_id}" not in response.text
    assert reads.calls[0][1][0] == OWNER_ALICE


@pytest.mark.parametrize("path, body_key, id_key, owned_id, foreign_id", LIST_ROUTES)
def test_a_list_refuses_a_foreign_workspace_selector_before_any_read(api, store, reads, monkeypatch, path, body_key, id_key, owned_id, foreign_id):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).get(f"{path}?workspace_id={OWNER_BOB}", headers=OPERATOR_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_authorized"
    assert reads.calls == []


@pytest.mark.parametrize("template, owned_id, foreign_id", DETAIL_ROUTES)
def test_a_by_id_read_of_a_foreign_record_answers_exactly_like_an_unknown_one(api, store, reads, monkeypatch, template, owned_id, foreign_id):
    _wire(api, monkeypatch, store, "wired")
    client = TestClient(api.app)

    owned = client.get(template.format(id=owned_id), headers=OPERATOR_HEADERS)
    foreign = client.get(template.format(id=foreign_id), headers=OPERATOR_HEADERS)
    unknown = client.get(template.format(id="missing-id"), headers=OPERATOR_HEADERS)

    assert owned.status_code == foreign.status_code == unknown.status_code == 200
    assert f"title for {owned_id}" in owned.text
    assert f"title for {foreign_id}" not in foreign.text
    # Only the echoed id may differ between a foreign and an unknown answer.
    assert foreign.text.replace(foreign_id, "<id>") == unknown.text.replace("missing-id", "<id>")


def test_neighbours_hide_a_foreign_node_and_a_foreign_neighbour(api, store, reads, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    client = TestClient(api.app)

    owned = client.get("/api/intelligence/knowledge-graph/nodes/node-alice/neighbors", headers=OPERATOR_HEADERS)
    foreign = client.get("/api/intelligence/knowledge-graph/nodes/node-bob/neighbors", headers=OPERATOR_HEADERS)
    unknown = client.get("/api/intelligence/knowledge-graph/nodes/missing-id/neighbors", headers=OPERATOR_HEADERS)

    assert owned.status_code == foreign.status_code == unknown.status_code == 200
    assert [node["node_id"] for node in owned.json()["nodes"]] == ["node-alice-2", "node-alice-3"]
    assert foreign.json() == unknown.json() == {"nodes": []}
    # Only the verified node's neighbours are read, and the read is not limited before the ownership filter.
    assert _calls(reads, "knowledge.neighbors") == [("node-alice", None, "both", 500)]


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_neighbour_count_does_not_reveal_a_foreign_link(api, store, reads, monkeypatch, limit):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).get(f"/api/intelligence/knowledge-graph/nodes/node-alice/neighbors?limit={limit}", headers=OPERATOR_HEADERS)

    # The node has two owned neighbours and one foreign link. The count is min(limit, owned), never less.
    assert response.status_code == 200
    assert [node["node_id"] for node in response.json()["nodes"]] == ["node-alice-2", "node-alice-3"][:limit]


def test_features_extract_answers_a_foreign_opportunity_exactly_like_a_missing_one(api, store, reads, monkeypatch):
    _wire(api, monkeypatch, store, "wired")
    client = TestClient(api.app)

    foreign = client.post(EXTRACT_PATH, json={"opportunity_id": "opp-bob"}, headers=OPERATOR_HEADERS)
    missing = client.post(EXTRACT_PATH, json={"opportunity_id": "opp-missing"}, headers=OPERATOR_HEADERS)

    assert foreign.status_code == missing.status_code == 200
    assert foreign.json() == missing.json()


@pytest.mark.parametrize("path", ["/api/intelligence", "/api/creative-intelligence", "/api/commercial-intelligence"])
def test_every_get_route_under_the_intelligence_prefixes_depends_on_its_gate(api, path):
    import api.routes.commercial_intelligence as commercial_routes
    import api.routes.creative_intelligence as creative_routes
    import api.routes.intelligence as intelligence_routes

    routers = (intelligence_routes.router, creative_routes.router, commercial_routes.router)
    gate = GATE_BY_PREFIX[path]
    gets = [route for router in routers for route in router.routes if isinstance(route, APIRoute) and "GET" in route.methods and route.path.startswith(path)]
    assert gets, f"no GET routes found under {path}"
    for route in gets:
        assert gate in _dependency_calls(route), f"GET {route.path} does not depend on its operator gate"


def test_every_get_route_under_the_intelligence_prefixes_is_covered_by_these_tests(api):
    import api.routes.commercial_intelligence as commercial_routes
    import api.routes.creative_intelligence as creative_routes
    import api.routes.intelligence as intelligence_routes

    routers = (intelligence_routes.router, creative_routes.router, commercial_routes.router)
    gets = sorted(route.path for router in routers for route in router.routes if isinstance(route, APIRoute) and "GET" in route.methods)
    # 15 list routes, 11 by-ID routes and the neighbours route. A new GET under these prefixes fails here until it is tested.
    assert len(gets) == len(LIST_ROUTES) + len(DETAIL_ROUTES) + 1 == 27


def test_features_extract_refuses_a_foreign_workspace_before_the_engine_runs(api, store, reads, monkeypatch):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).post(EXTRACT_PATH, json={"workspace_id": OWNER_BOB}, headers=OPERATOR_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "workspace_not_authorized"
    assert reads.calls == []


def test_features_extract_binds_the_verified_workspace_and_drops_a_foreign_opportunity(api, store, reads, monkeypatch):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).post(EXTRACT_PATH, json={"opportunity_id": "opp-bob"}, headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    args = _calls(reads, "commercial.extract_features")[0]
    assert args[0] == OWNER_ALICE and args[1] is None


def test_features_extract_passes_a_verified_workspace_opportunity_to_the_engine(api, store, reads, monkeypatch):
    _wire(api, monkeypatch, store, "wired")

    response = TestClient(api.app).post(EXTRACT_PATH, json={"workspace_id": OWNER_ALICE, "opportunity_id": "opp-alice"}, headers=OPERATOR_HEADERS)

    assert response.status_code == 200
    args = _calls(reads, "commercial.extract_features")[0]
    assert args[0] == OWNER_ALICE and args[1] == "opp-alice"
