"""Canonical event reads are operator-only and bound to the verified principal's workspace.

Synthetic principals, memberships and events only. The verifier and repository are fakes injected through
``app.dependency_overrides``; the JSONL source is a file under ``tmp_path`` that ``ARTIFACTS`` points at, so no
real artifact, credential or configuration file is read. Denied requests must never reach the event loader.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes import canonical_events
from backend.contracts.events import Event
from backend.events.query_models import EventQuery
from backend.events.query_service import WorkspaceScopeError, bind_query_to_workspace
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR, ROLE_PERMISSIONS, CANONICAL_EVENT_READ, role_grants
from backend.identity.workspaces import WorkspaceAccess
from backend.security.rate_limit import reset_rate_limits_for_tests

ISSUER = "https://clerk.test"
BOUND_WS = "ws_ops_synthetic"
OTHER_WS = "ws_other_synthetic"
CANARY = "synthetic-canary-payload-7c1e"

READ_PATHS = [
    "/api/events",
    "/api/events/timeline",
    "/api/events/commerce-runs",
    "/api/events/shopify-imports",
    "/api/events/supplier-evidence",
    "/api/events/opportunity-rankings",
    "/api/events/opportunity-scoring",
    "/api/events/competition-evidence",
    "/api/events/competition-summaries",
    "/api/events/research-portfolio",
    "/api/events/product-research",
    "/api/events/readiness",
]

# token -> principal subject. Memberships below are the only authority the gate reads.
TOKENS = {
    "tok-operator": "user_operator",
    "tok-viewer": "user_viewer",
    "tok-norole": "user_norole",
    "tok-unknown-role": "user_unknown_role",
    "tok-client-op": "user_client_op",
    "tok-outsider": "user_outsider",
    "tok-multi": "user_multi",
    "tok-explodes": "user_explodes",
}
MEMBERSHIPS = {
    "user_operator": [(BOUND_WS, "internal", INTERNAL_OPERATOR)],
    "user_viewer": [(BOUND_WS, "internal", CLIENT_VIEWER)],
    "user_norole": [(BOUND_WS, "internal", None)],
    "user_unknown_role": [(BOUND_WS, "internal", "owner")],
    "user_client_op": [(OTHER_WS, "client_service", INTERNAL_OPERATOR)],
    "user_multi": [(BOUND_WS, "internal", INTERNAL_OPERATOR), (OTHER_WS, "internal", INTERNAL_OPERATOR)],
}
OPERATOR_TOKEN = {"Authorization": "Bearer tok-operator"}


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        if token == "tok-explodes":
            # The verifier's own text must never reach a client response.
            raise RuntimeError(f"verifier bug {CANARY}")
        try:
            return VerifiedPrincipal(ISSUER, TOKENS[token])
        except KeyError:
            raise IdentityError() from None


class FakeRepo:
    def memberships_for(self, principal: VerifiedPrincipal) -> list[WorkspaceAccess]:
        return [
            WorkspaceAccess(ISSUER, principal.subject, ws, ws_type, "synthetic", role)
            for ws, ws_type, role in MEMBERSHIPS.get(principal.subject, [])
        ]


def _app(*, identity: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(canonical_events.router)
    if identity:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
        app.dependency_overrides[get_workspace_repository] = lambda: FakeRepo()
    return app


def _probe(event_id: str, workspace_id: str, occurred_at: float) -> Event:
    # "synthetic_probe" belongs to no summary section, so its payload is only ever shown as keys.
    return Event(
        event_id,
        workspace_id,
        "synthetic",
        event_id,
        "synthetic_probe",
        1,
        occurred_at,
        source="synthetic_test",
        payload={"secret": CANARY},
    )


@pytest.fixture(autouse=True)
def _rate_limit_isolated(monkeypatch):
    monkeypatch.setenv("MARKETOS_EVENT_READ_RATE_LIMIT", "100000")
    reset_rate_limits_for_tests()
    yield
    reset_rate_limits_for_tests()


@pytest.fixture
def jsonl(monkeypatch, tmp_path: Path) -> Path:
    artifacts = (tmp_path / "artifacts").resolve()
    artifacts.mkdir()
    path = artifacts / "events.jsonl"
    rows = [
        _probe("evt_ops_1", BOUND_WS, 1.0),
        _probe("evt_other_1", OTHER_WS, 2.0),
        _probe("evt_ops_2", BOUND_WS, 3.0),
    ]
    path.write_text("".join(json.dumps(row.to_dict(), sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    monkeypatch.setattr(canonical_events, "ARTIFACTS", artifacts)
    monkeypatch.setenv("MARKETOS_EVENT_READ_JSONL_PATH", str(path))
    return path


@pytest.fixture
def loads(monkeypatch) -> list[str]:
    """Record every JSONL load attempt; denied requests must leave this empty."""
    calls: list[str] = []
    original = canonical_events.load_events_from_jsonl

    def spy(path, **kwargs):
        calls.append(str(path))
        return original(path, **kwargs)

    monkeypatch.setattr(canonical_events, "load_events_from_jsonl", spy)
    return calls


def _event_ids(response) -> set[str]:
    return {event["event_id"] for event in response.json()["timeline"]["events"]}


@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Basic c3ludGhldGlj"},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer tok-unknown"},
    ],
)
def test_unauthenticated_requests_are_refused_before_any_read(jsonl, loads, path, headers):
    response = TestClient(_app()).get(path, headers=headers)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] in {"missing_credentials", "invalid_credentials"}
    assert response.headers.get("www-authenticate") == "Bearer"
    assert loads == []


@pytest.mark.parametrize("path", READ_PATHS)
def test_unconfigured_identity_provider_fails_closed(jsonl, loads, path):
    response = TestClient(_app(identity=False)).get(path, headers=OPERATOR_TOKEN)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "identity_provider_unavailable"}}
    assert loads == []


def test_verifier_failure_is_a_plain_401_that_echoes_nothing(jsonl, loads):
    response = TestClient(_app()).get("/api/events", headers={"Authorization": "Bearer tok-explodes"})

    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_credentials"}}
    assert CANARY not in response.text
    assert str(jsonl) not in response.text
    assert loads == []


@pytest.mark.parametrize(
    ("token", "code"),
    [
        ("tok-viewer", "role_not_authorized"),
        ("tok-norole", "role_not_authorized"),
        ("tok-unknown-role", "role_not_authorized"),
        ("tok-client-op", "no_workspace_membership"),
        ("tok-outsider", "no_workspace_membership"),
        ("tok-multi", "workspace_ambiguous"),
    ],
)
def test_principals_without_a_sole_operator_membership_are_denied(jsonl, loads, token, code):
    response = TestClient(_app()).get("/api/events", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": code}}
    assert loads == []


def test_operator_reads_only_the_bound_workspace_without_a_selector(jsonl, loads):
    response = TestClient(_app()).get("/api/events", headers=OPERATOR_TOKEN)

    assert response.status_code == 200
    assert response.json()["query"]["workspace_id"] == BOUND_WS
    assert _event_ids(response) == {"evt_ops_1", "evt_ops_2"}
    assert "evt_other_1" not in response.text
    assert loads == [str(jsonl)]


@pytest.mark.parametrize("path", READ_PATHS[:-1])
@pytest.mark.parametrize("selector", [OTHER_WS, "", BOUND_WS.upper(), f"{BOUND_WS} "])
def test_forged_workspace_selector_is_refused_on_every_read(jsonl, loads, path, selector):
    response = TestClient(_app()).get(path, params={"workspace_id": selector}, headers=OPERATOR_TOKEN)

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "workspace_not_authorized"}}
    assert "evt_other_1" not in response.text
    assert loads == []


def test_selector_naming_the_bound_workspace_is_accepted(jsonl, loads):
    client = TestClient(_app())
    unscoped = client.get("/api/events", headers=OPERATOR_TOKEN)
    selected = client.get("/api/events", params={"workspace_id": BOUND_WS}, headers=OPERATOR_TOKEN)

    assert selected.status_code == 200
    assert _event_ids(selected) == _event_ids(unscoped) == {"evt_ops_1", "evt_ops_2"}


def test_headers_cannot_select_another_workspace(jsonl, loads):
    response = TestClient(_app()).get(
        "/api/events",
        headers={**OPERATOR_TOKEN, "X-MarketOS-Workspace": OTHER_WS, "X-Workspace-Id": OTHER_WS},
    )

    assert response.status_code == 200
    assert _event_ids(response) == {"evt_ops_1", "evt_ops_2"}


def test_supabase_source_receives_only_the_bound_query(monkeypatch, jsonl):
    seen: list[EventQuery] = []

    def fake_supabase(query):
        seen.append(query)
        return {"timeline": {"events": []}, "read_only": True}

    monkeypatch.setattr(canonical_events, "query_supabase_canonical_events", fake_supabase)
    client = TestClient(_app())

    unscoped = client.get("/api/events", params={"source": "supabase_staging"}, headers=OPERATOR_TOKEN)
    forged = client.get(
        "/api/events", params={"source": "supabase_staging", "workspace_id": OTHER_WS}, headers=OPERATOR_TOKEN
    )

    assert unscoped.status_code == 200
    assert [query.workspace_id for query in seen] == [BOUND_WS]
    assert forged.status_code == 403
    assert len(seen) == 1


def test_denied_and_allowed_reads_never_write(jsonl, loads, tmp_path):
    def snapshot() -> dict[str, str]:
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    before = snapshot()
    client = TestClient(_app())
    for headers, params in [
        (OPERATOR_TOKEN, {}),
        (OPERATOR_TOKEN, {"workspace_id": OTHER_WS}),
        ({}, {}),
        ({"Authorization": "Bearer tok-viewer"}, {}),
    ]:
        client.get("/api/events", params=params, headers=headers)

    assert snapshot() == before


def test_denied_responses_carry_only_fixed_codes(jsonl):
    client = TestClient(_app())
    responses = [
        client.get("/api/events"),
        client.get("/api/events", headers={"Authorization": "Bearer tok-viewer"}),
        client.get("/api/events", params={"workspace_id": OTHER_WS}, headers=OPERATOR_TOKEN),
    ]

    assert [response.status_code for response in responses] == [401, 403, 403]
    for response in responses:
        assert set(response.json()) == {"detail"}
        assert set(response.json()["detail"]) == {"code"}
        assert str(jsonl) not in response.text


def test_allowed_responses_show_payload_keys_not_values(jsonl):
    response = TestClient(_app()).get("/api/events", headers=OPERATOR_TOKEN)

    assert response.status_code == 200
    assert CANARY not in response.text
    assert str(jsonl) not in response.text


def test_bind_query_limits_to_the_bound_workspace_and_refuses_widening():
    base = EventQuery(None, None, None, None, None, None, 10, 0)

    bound = bind_query_to_workspace(base, BOUND_WS)
    assert bound.workspace_id == BOUND_WS
    assert (
        bind_query_to_workspace(
            EventQuery(BOUND_WS, "synthetic_probe", None, None, None, None, 5, 2), BOUND_WS
        ).event_type
        == "synthetic_probe"
    )

    with pytest.raises(WorkspaceScopeError):
        bind_query_to_workspace(EventQuery(OTHER_WS, None, None, None, None, None, 10, 0), BOUND_WS)
    for missing in (None, "", 0):
        with pytest.raises(WorkspaceScopeError):
            bind_query_to_workspace(base, missing)


def test_event_read_is_operator_only_by_role_map():
    assert role_grants(INTERNAL_OPERATOR, CANONICAL_EVENT_READ)
    assert not role_grants(CLIENT_VIEWER, CANONICAL_EVENT_READ)
    assert CANONICAL_EVENT_READ not in ROLE_PERMISSIONS[CLIENT_VIEWER]
