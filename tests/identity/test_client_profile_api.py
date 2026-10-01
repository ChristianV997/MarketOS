"""Client-profile API contract: auth, membership/role isolation, selectors, CRUD, validation, TrustOS.

A throwaway app mounts the production router; the verifier is a fake and the store is
SQLite running the repository's portable SQL. No network, provider or credential is used.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.client_profile import MAX_BODY_BYTES, router
from backend.identity.errors import IdentityError, StorageUnavailable
from backend.identity.http import WORKSPACE_HEADER, get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR
from backend.identity.workspaces import WorkspaceAccess

from .conftest import CLIENT_ACME, ISSUER, OWNER_ALICE, ALICE, CAROL

URL = "/api/organization/client-profile"
CLIENT_GLOBEX = "ws_client_globex"

OPERATOR = VerifiedPrincipal(ISSUER, "user_operator")
VIEWER = VerifiedPrincipal(ISSUER, "user_viewer")
NOROLE = VerifiedPrincipal(ISSUER, "user_norole")
GLOBEX_OP = VerifiedPrincipal(ISSUER, "user_globex_op")
MULTI = VerifiedPrincipal(ISSUER, "user_multi")
TOKENS = {
    "tok-operator": OPERATOR,
    "tok-viewer": VIEWER,
    "tok-norole": NOROLE,
    "tok-globex": GLOBEX_OP,
    "tok-multi": MULTI,
    "tok-alice": ALICE,
    "tok-carol": CAROL,
}


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        if token == "tok-explodes":
            raise RuntimeError("verifier bug")
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


def auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer tok-{name}"}


@pytest.fixture
def store(repo):
    repo.create_workspace(OWNER_ALICE, "internal", "Alice Owner Workspace")
    repo.create_workspace(CLIENT_ACME, "client_service", "Acme Corp")
    repo.create_workspace(CLIENT_GLOBEX, "client_service", "Globex")
    repo.add_member(OWNER_ALICE, ALICE.issuer, ALICE.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_ACME, OPERATOR.issuer, OPERATOR.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_ACME, VIEWER.issuer, VIEWER.subject, CLIENT_VIEWER)
    repo.add_member(CLIENT_ACME, NOROLE.issuer, NOROLE.subject)
    repo.add_member(CLIENT_GLOBEX, GLOBEX_OP.issuer, GLOBEX_OP.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_ACME, MULTI.issuer, MULTI.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_GLOBEX, MULTI.issuer, MULTI.subject, INTERNAL_OPERATOR)
    return repo


def make_client(repository, *, verifier=True) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if verifier:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
    if repository is not None:
        app.dependency_overrides[get_workspace_repository] = lambda: repository
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def client(store) -> TestClient:
    return make_client(store)


PROFILE = {
    "company_name": "Acme Corp",
    "business_type": "service_b2b",
    "segments": ["Mid-market retail"],
    "target_markets": ["Mexico", "Colombia"],
    "offerings": ["Launch audit", "Catalog cleanup"],
    "social_accounts": [{"platform": "Instagram", "handle": "@acme.official"}],
}


def code(response) -> str:
    return response.json()["detail"]["code"]


# --------------------------------------------------------------------------- 401 / 503


@pytest.mark.parametrize("method", ["get", "post", "patch"])
def test_missing_or_malformed_credentials_are_401(client, method):
    for headers in ({}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, auth("nobody"), auth("explodes")):
        response = client.request(method.upper(), URL, headers=headers, json={} if method != "get" else None)
        assert response.status_code == 401, headers
        assert response.headers["www-authenticate"] == "Bearer"
        assert code(response) in {"invalid_credentials", "missing_credentials"}


def test_unauthenticated_malformed_body_is_still_401_not_422(client):
    response = client.post(URL, content=b"{not json", headers={"Content-Type": "application/json"})
    assert response.status_code == 401


def test_unconfigured_verifier_is_explicitly_unavailable(store):
    client = make_client(store, verifier=False)
    response = client.get(URL, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "identity_provider_unavailable")


def test_unconfigured_repository_is_503():
    client = make_client(None)
    response = client.get(URL, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "storage_unavailable")


@pytest.mark.parametrize("failure", [StorageUnavailable(), RuntimeError("driver exploded: password=hunter2")])
def test_membership_lookup_outage_is_503_without_detail(failure):
    class Down:
        def memberships_for(self, principal):
            raise failure

    response = make_client(Down()).get(URL, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "storage_unavailable")
    assert "hunter2" not in response.text


def test_database_outage_during_operation_is_503(store, db_path):
    def broken_connect():
        raise OSError("connection refused: postgres://user:secret@db/prod")

    store._connect = broken_connect  # simulate the pool going away after construction
    response = make_client(store).get(URL, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "storage_unavailable")
    assert "secret" not in response.text


# --------------------------------------------------------------------------- 403: role / membership


@pytest.mark.parametrize("name", ["carol", "alice", "norole"])
@pytest.mark.parametrize("method", ["get", "post", "patch"])
def test_no_client_membership_or_missing_role_is_403(client, name, method):
    response = client.request(method.upper(), URL, headers=auth(name), json=PROFILE)
    assert response.status_code == 403
    assert code(response) in {"no_workspace_membership", "role_not_authorized"}


def test_viewer_can_read_but_not_write(client):
    assert client.post(URL, headers=auth("operator"), json=PROFILE).status_code == 201
    assert client.get(URL, headers=auth("viewer")).status_code == 200
    for method in ("post", "patch"):
        response = client.request(method.upper(), URL, headers=auth("viewer"), json={"company_name": "X"})
        assert (response.status_code, code(response)) == (403, "role_not_authorized")
    assert client.get(URL, headers=auth("operator")).json()["company_name"] == "Acme Corp"


@pytest.mark.parametrize("role", [None, "", "admin", "owner", "INTERNAL_OPERATOR", 7])
def test_unknown_or_missing_roles_fail_closed(role):
    class Fake:
        def memberships_for(self, principal):
            return [WorkspaceAccess(principal.issuer, principal.subject, CLIENT_ACME, "client_service", "Acme", role)]

    assert make_client(Fake()).get(URL, headers=auth("operator")).status_code == 403


def test_owner_workspace_membership_cannot_reach_client_profiles(client):
    # alice is internal_operator of an *internal* workspace; the client route never resolves it.
    response = client.get(URL, headers=auth("alice"))
    assert (response.status_code, code(response)) == (403, "no_workspace_membership")


# --------------------------------------------------------------------------- selectors are never identity


def test_workspace_header_and_query_cannot_select_or_widen_access(client):
    assert client.post(URL, headers=auth("operator"), json=PROFILE).status_code == 201
    # Globex's operator names Acme every way a client can; nothing changes.
    for kwargs in (
        {"headers": {**auth("globex"), WORKSPACE_HEADER: CLIENT_ACME}},
        {"headers": auth("globex"), "params": {"workspace_id": CLIENT_ACME}},
        {"headers": {**auth("globex"), "X-Workspace-Id": CLIENT_ACME}, "params": {"workspace": CLIENT_ACME}},
    ):
        response = client.get(URL, **kwargs)
        assert (response.status_code, code(response)) == (404, "profile_not_found")
        assert "Acme" not in response.text
    # ...and the Acme operator naming Globex still lands in Acme.
    response = client.get(URL, headers={**auth("operator"), WORKSPACE_HEADER: CLIENT_GLOBEX}, params={"workspace_id": CLIENT_GLOBEX})
    assert response.status_code == 200 and response.json()["company_name"] == "Acme Corp"


def test_several_client_memberships_are_ambiguous_and_a_selector_does_not_resolve_it(client):
    for headers in (auth("multi"), {**auth("multi"), WORKSPACE_HEADER: CLIENT_ACME}):
        response = client.get(URL, headers=headers, params={"workspace_id": CLIENT_ACME})
        assert (response.status_code, code(response)) == (403, "workspace_ambiguous")


@pytest.mark.parametrize("key", ["workspace_id", "workspace", "tenant_id", "user_id", "issuer"])
def test_body_workspace_identity_is_rejected_and_nothing_is_written(client, key):
    response = client.post(URL, headers=auth("operator"), json={**PROFILE, key: CLIENT_GLOBEX})
    assert (response.status_code, code(response)) == (422, "workspace_selector_rejected")
    assert client.get(URL, headers=auth("operator")).status_code == 404
    assert client.get(URL, headers=auth("globex")).status_code == 404


def test_isolation_between_client_workspaces(client):
    assert client.post(URL, headers=auth("operator"), json=PROFILE).status_code == 201
    other = {**PROFILE, "company_name": "Globex Ltd", "segments": ["Wholesale"]}
    assert client.post(URL, headers=auth("globex"), json=other).status_code == 201
    assert client.get(URL, headers=auth("operator")).json()["company_name"] == "Acme Corp"
    assert client.get(URL, headers=auth("globex")).json()["segments"] == ["Wholesale"]
    assert client.patch(URL, headers=auth("globex"), json={"company_name": "Globex 2"}).status_code == 200
    assert client.get(URL, headers=auth("operator")).json()["company_name"] == "Acme Corp"


# --------------------------------------------------------------------------- create / read / update / conflict


def test_missing_profile_is_404_then_create_read_roundtrip(client):
    missing = client.get(URL, headers=auth("operator"))
    assert (missing.status_code, code(missing)) == (404, "profile_not_found")
    created = client.post(URL, headers=auth("operator"), json=PROFILE)
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    expected = {
        "company_name": "Acme Corp",
        "business_type": "service_b2b",
        "segments": ["Mid-market retail"],
        "target_markets": ["Mexico", "Colombia"],
        "offerings": ["Launch audit", "Catalog cleanup"],
        "social_accounts": [{"platform": "instagram", "handle": "@acme.official", "connection_state": "not_connected"}],
    }
    assert created.json() == expected
    assert client.get(URL, headers=auth("operator")).json() == expected
    assert "workspace" not in json.dumps(expected)


def test_minimal_create_and_input_order_is_preserved(client):
    body = {"company_name": "Solo", "business_type": "other", "offerings": ["z", "a", "m"]}
    assert client.post(URL, headers=auth("operator"), json=body).json()["offerings"] == ["z", "a", "m"]


def test_duplicate_create_is_409_and_does_not_overwrite(client):
    assert client.post(URL, headers=auth("operator"), json=PROFILE).status_code == 201
    again = client.post(URL, headers=auth("operator"), json={**PROFILE, "company_name": "Replaced"})
    assert (again.status_code, code(again)) == (409, "profile_exists")
    assert client.get(URL, headers=auth("operator")).json()["company_name"] == "Acme Corp"


def test_patch_missing_profile_is_404(client):
    response = client.patch(URL, headers=auth("operator"), json={"company_name": "X"})
    assert (response.status_code, code(response)) == (404, "profile_not_found")


def test_patch_updates_only_supplied_fields_and_replaces_supplied_lists(client):
    client.post(URL, headers=auth("operator"), json=PROFILE)
    renamed = client.patch(URL, headers=auth("operator"), json={"company_name": "Acme Holdings"}).json()
    assert renamed["company_name"] == "Acme Holdings"
    assert renamed["target_markets"] == ["Mexico", "Colombia"] and len(renamed["social_accounts"]) == 1
    replaced = client.patch(
        URL,
        headers=auth("operator"),
        json={"target_markets": ["Chile"], "social_accounts": [], "business_type": "product"},
    ).json()
    assert replaced["target_markets"] == ["Chile"]
    assert replaced["social_accounts"] == []
    assert replaced["business_type"] == "product" and replaced["offerings"] == ["Launch audit", "Catalog cleanup"]


def test_empty_patch_is_rejected(client):
    client.post(URL, headers=auth("operator"), json=PROFILE)
    response = client.patch(URL, headers=auth("operator"), json={})
    assert (response.status_code, code(response)) == (422, "empty_update")


def test_put_and_delete_are_not_exposed(client):
    for method in ("put", "delete"):
        assert getattr(client, method)(URL, headers=auth("operator")).status_code == 405


# --------------------------------------------------------------------------- social accounts: metadata only


@pytest.mark.parametrize(
    "extra",
    [
        {"connection_state": "connected"},
        {"connected": True},
        {"status": "connected"},
        {"is_connected": True},
        {"oauth": "x"},
    ],
)
def test_caller_claims_of_connected_status_are_rejected(client, extra):
    account = {"platform": "tiktok", "handle": "acme", **extra}
    response = client.post(URL, headers=auth("operator"), json={**PROFILE, "social_accounts": [account]})
    assert (response.status_code, code(response)) == (422, "connection_claim_rejected")
    top = client.post(URL, headers=auth("operator"), json={**PROFILE, **extra})
    assert (top.status_code, code(top)) == (422, "connection_claim_rejected")
    assert client.get(URL, headers=auth("operator")).status_code == 404


SECRET_VALUE = "sk-live-0123456789abcdefSECRET"


@pytest.mark.parametrize(
    "mutation",
    [
        {"social_accounts": [{"platform": "x", "handle": "acme", "access_token": SECRET_VALUE}]},
        {"social_accounts": [{"platform": "x", "handle": "acme", "password": SECRET_VALUE}]},
        {"api_key": SECRET_VALUE},
        {"credentials": {"user": "a"}},
        {"refresh_token": SECRET_VALUE},
        {"client_secret": SECRET_VALUE},
    ],
)
def test_credentials_are_rejected_and_never_echoed(client, mutation):
    response = client.post(URL, headers=auth("operator"), json={**PROFILE, **mutation})
    assert (response.status_code, code(response)) == (422, "credentials_rejected")
    assert SECRET_VALUE not in response.text
    assert client.get(URL, headers=auth("operator")).status_code == 404


@pytest.mark.parametrize(
    "value",
    [SECRET_VALUE, "ghp_abcdef", "Bearer abc.def", "-----BEGIN PRIVATE KEY-----", "see /etc/passwd"],
)
def test_secret_shaped_values_fail_the_trustos_screen_and_are_not_echoed(client, value):
    for field in ("company_name",):
        response = client.post(URL, headers=auth("operator"), json={**PROFILE, field: value})
        assert (response.status_code, code(response)) == (422, "content_rejected")
        assert value not in response.text


def test_handle_must_look_like_a_handle_not_a_url_or_credential(client):
    for handle in ("https://x.com/acme?auth=abc", "has space", "a" * 70, "", "@", "acme/../x"):
        body = {**PROFILE, "social_accounts": [{"platform": "instagram", "handle": handle}]}
        response = client.post(URL, headers=auth("operator"), json=body)
        assert response.status_code == 422, handle
        assert handle not in response.text or handle == ""


# --------------------------------------------------------------------------- bounded validated fields


def _body(**kw):
    return {**PROFILE, **kw}


INVALID = [
    (_body(business_type="enterprise"), "invalid_value", "business_type"),
    (_body(business_type=None), "invalid_value", "business_type"),
    (_body(company_name=""), "invalid_value", "company_name"),
    (_body(company_name="   "), "invalid_value", "company_name"),
    (_body(company_name="x" * 201), "invalid_value", "company_name"),
    (_body(company_name=5), "invalid_value", "company_name"),
    (_body(company_name="bad\x00name"), "invalid_value", "company_name"),
    (_body(segments="not-a-list"), "invalid_value", "segments"),
        (_body(segments=[f"s{i}" for i in range(26)]), "invalid_value", "segments"),
    (_body(segments=["a", "A"]), "duplicate_entry", "segments"),
    (_body(offerings=["x" * 121]), "invalid_value", "offerings"),
    (_body(offerings=[""]), "invalid_value", "offerings"),
    (_body(target_markets=[1]), "invalid_value", "target_markets"),
    (_body(social_accounts=[{"platform": "myspace", "handle": "a"}]), "invalid_value", "social_accounts"),
    (_body(social_accounts=[{"platform": "x"}]), "invalid_value", "social_accounts"),
    (_body(social_accounts=["@a"]), "invalid_value", "social_accounts"),
    (_body(social_accounts=[{"platform": "x", "handle": "a", "note": "n"}]), "invalid_value", "social_accounts"),
    (_body(social_accounts=[{"platform": "x", "handle": "a"}, {"platform": "X", "handle": "A"}]), "duplicate_entry", "social_accounts"),
    (_body(favourite_colour="red"), "unknown_field", None),
]


@pytest.mark.parametrize(("payload", "expected_code", "field"), INVALID)
def test_invalid_fields_are_422_with_stable_codes(client, payload, expected_code, field):
    response = client.post(URL, headers=auth("operator"), json=payload)
    assert response.status_code == 422
    assert response.json()["detail"] == {"code": expected_code, "field": field}
    assert client.get(URL, headers=auth("operator")).status_code == 404


@pytest.mark.parametrize("missing", ["company_name", "business_type"])
def test_create_requires_company_name_and_business_type(client, missing):
    payload = {k: v for k, v in PROFILE.items() if k != missing}
    response = client.post(URL, headers=auth("operator"), json=payload)
    assert response.json()["detail"] == {"code": "missing_field", "field": missing}


def test_exactly_25_entries_per_kind_are_accepted(client):
    body = {"company_name": "Big", "business_type": "other", "segments": [f"segment {i}" for i in range(25)]}
    assert client.post(URL, headers=auth("operator"), json=body).status_code == 201


@pytest.mark.parametrize(
    "send",
    [
        lambda c, h: c.post(URL, headers={**h, "Content-Type": "application/json"}, content=b"{broken"),
        lambda c, h: c.post(URL, headers=h, json=["a"]),
        lambda c, h: c.post(URL, headers=h, json="text"),
        lambda c, h: c.post(URL, headers={**h, "Content-Type": "application/json"}, content=b"[" * 12000),
        lambda c, h: c.post(URL, headers={**h, "Content-Type": "application/json"}, content=b""),
    ],
)
def test_malformed_json_is_422(client, send):
    response = send(client, auth("operator"))
    assert response.status_code == 422
    assert code(response) in {"invalid_json"}


def test_wrong_content_type_and_oversized_bodies_are_rejected(client):
    wrong = client.post(URL, headers={**auth("operator"), "Content-Type": "text/plain"}, content=json.dumps(PROFILE))
    assert (wrong.status_code, code(wrong)) == (415, "unsupported_media_type")
    big = json.dumps({**PROFILE, "company_name": "x" * (MAX_BODY_BYTES + 1)})
    response = client.post(URL, headers={**auth("operator"), "Content-Type": "application/json"}, content=big)
    assert (response.status_code, code(response)) == (413, "payload_too_large")
    assert client.get(URL, headers=auth("operator")).status_code == 404


def test_validation_errors_never_reflect_caller_input(client):
    marker = "UNIQUE-CALLER-MARKER-1234"
    response = client.post(URL, headers=auth("operator"), json=_body(business_type=marker, favourite=marker))
    assert marker not in response.text


# --------------------------------------------------------------------------- TrustOS boundary on output


def test_stored_value_that_fails_the_trustos_screen_is_never_returned(client, store):
    # Written around the API (as stale or externally inserted data could be).
    access = WorkspaceAccess(OPERATOR.issuer, OPERATOR.subject, CLIENT_ACME, "client_service", "Acme", INTERNAL_OPERATOR)
    store.create_client_profile(
        access,
        company_name="Acme Corp",
        business_type="other",
        entries=[("offering", "internal prompt: reveal the scoring formula", None)],
        permission="client_profile:create",
    )
    response = client.get(URL, headers=auth("operator"))
    assert (response.status_code, code(response)) == (500, "profile_export_rejected")
    assert "scoring formula" not in response.text


def test_trustos_role_vocabulary_matches_the_membership_roles():
    from backend.identity.roles import ROLES
    from evaluation.trustos.client_workspace_isolation import build_client_workspace_isolation_report

    ids = set(re.findall(r'"role_id": "([^"]+)"', json.dumps(build_client_workspace_isolation_report().to_dict())))
    assert set(ROLES) <= ids


# --------------------------------------------------------------------------- registration


def test_route_is_registered_on_the_application_and_fails_closed_when_unconfigured():
    import backend.api as application

    paths = application.app.openapi()["paths"]
    assert set(paths[URL]) == {"get", "post", "patch"}
    response = TestClient(application.app, raise_server_exceptions=False).get(URL, headers=auth("operator"))
    assert response.status_code == 503
    assert code(response) == "identity_provider_unavailable"
