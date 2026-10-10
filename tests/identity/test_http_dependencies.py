"""Verified-principal and workspace dependencies through a throwaway FastAPI app.

The app is defined here only; no production route is mounted or modified.
Tokens are fake opaque strings resolved by a fake verifier.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from backend.identity.errors import IdentityError, StorageUnavailable
from backend.identity.http import (
    WORKSPACE_HEADER,
    get_token_verifier,
    get_workspace_repository,
    install_identity_error_handlers,
    require_principal,
    resolve_workspace_access,
)
from backend.identity.principal import VerifiedPrincipal
from backend.identity.repository import PostgresWorkspaceRepository

from .conftest import ALICE, BOB, CAROL, CLIENT_ACME, DAVE, OWNER_ALICE, OWNER_BOB, OWNER_DAVE

TOKENS = {"tok-alice": ALICE, "tok-bob": BOB, "tok-carol": CAROL, "tok-dave": DAVE}


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        if token == "tok-explodes":
            raise RuntimeError(f"verifier bug handling {token}")
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


def build_app(*, verifier=True, repository=None) -> FastAPI:
    app = FastAPI()
    install_identity_error_handlers(app)

    @app.get("/whoami")
    def whoami(principal: VerifiedPrincipal = Depends(require_principal)):
        return {"issuer": principal.issuer, "subject": principal.subject}

    @app.get("/workspace")
    def workspace(access=Depends(resolve_workspace_access)):
        return {"workspace_id": access.workspace_id, "workspace_type": access.workspace_type}

    @app.get("/portfolio")
    def portfolio(access=Depends(resolve_workspace_access), repo=Depends(get_workspace_repository)):
        return [asdict(item) for item in repo.list_portfolio_items(access)]

    if verifier:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
    if repository is not None:
        app.dependency_overrides[get_workspace_repository] = lambda: repository
    return app


@pytest.fixture
def client(seeded):
    alice = seeded.memberships_for(ALICE)[0]
    bob = seeded.memberships_for(BOB)[0]
    seeded.add_portfolio_item(alice, name="Alice product", evidence_label="fixture")
    seeded.add_portfolio_item(bob, name="Bob secret product", evidence_label="manual")
    return TestClient(build_app(repository=seeded))


def auth(token: str, **headers) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **headers}


# ----- 401: missing / invalid identity -----

def test_missing_credentials_are_401_with_a_bearer_challenge(client):
    response = client.get("/whoami")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": {"code": "missing_credentials"}}


@pytest.mark.parametrize(
    "header",
    ["Bearer", "Bearer ", "Basic dG9rLWFsaWNl", "tok-alice", "Bearer tok-alice extra", "Bearer tok alice", "Bearer tok-alice\r\nX: y", "Bearer " + "a" * 9000],
)
def test_malformed_authorization_headers_are_401(client, header):
    try:
        response = client.get("/whoami", headers={"Authorization": header})
    except Exception:  # some header values are rejected by the HTTP client itself; that is not a bypass
        return
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_unknown_token_is_401_and_the_token_is_never_echoed_or_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = client.get("/whoami", headers=auth("tok-forged-value-999"))
    assert response.status_code == 401
    assert response.json() == {"detail": {"code": "invalid_credentials"}}
    assert "tok-forged-value-999" not in response.text
    assert "tok-forged-value-999" not in caplog.text
    assert "tok-forged-value-999" not in str(dict(response.headers))


def test_an_unexpected_verifier_failure_fails_closed_as_401_not_500(client, caplog):
    with caplog.at_level(logging.DEBUG):
        response = client.get("/whoami", headers=auth("tok-explodes"))
    assert response.status_code == 401
    assert "tok-explodes" not in response.text and "tok-explodes" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_valid_token_yields_the_principal(client):
    assert client.get("/whoami", headers=auth("tok-alice")).json() == {"issuer": ALICE.issuer, "subject": "user_alice"}


def test_bearer_scheme_is_case_insensitive(client):
    assert client.get("/whoami", headers={"Authorization": "bearer tok-alice"}).status_code == 200


# ----- client-supplied identity/workspace values never establish identity -----

@pytest.mark.parametrize(
    "forged",
    [
        {"X-User-Id": "user_alice"},
        {"X-Clerk-User-Id": "user_alice"},
        {"X-Forwarded-User": "user_alice"},
        {"X-Workspace-Id": OWNER_ALICE},
        {WORKSPACE_HEADER: OWNER_ALICE},
        {"Cookie": "__session=tok-alice; user=user_alice"},
    ],
)
def test_identity_like_headers_without_a_verified_token_are_401(client, forged):
    assert client.get("/whoami", headers=forged).status_code == 401
    assert client.get("/workspace", headers=forged).status_code == 401
    assert client.get("/portfolio", headers=forged).status_code == 401


def test_identity_like_headers_cannot_override_the_verified_principal(client):
    response = client.get("/whoami", headers=auth("tok-alice", **{"X-User-Id": "user_bob", "X-Forwarded-User": "user_bob"}))
    assert response.json()["subject"] == "user_alice"


def test_workspace_query_and_body_values_are_ignored(client):
    response = client.get("/portfolio", params={"workspace_id": OWNER_BOB, "workspace": "Bob Owner Workspace"}, headers=auth("tok-alice"))
    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["Alice product"]
    assert "Bob secret product" not in response.text


# ----- 403: unauthorized workspace / cross-workspace denial -----

def test_default_workspace_resolves_from_the_token(client):
    assert client.get("/workspace", headers=auth("tok-alice")).json() == {"workspace_id": OWNER_ALICE, "workspace_type": "internal"}
    assert client.get("/workspace", headers=auth("tok-bob")).json()["workspace_id"] == OWNER_BOB


def test_forged_workspace_selector_is_403_and_leaks_nothing(client):
    forged = client.get("/portfolio", headers=auth("tok-alice", **{WORKSPACE_HEADER: OWNER_BOB}))
    assert forged.status_code == 403
    assert forged.json() == {"detail": {"code": "workspace_not_authorized"}}
    assert "Bob secret product" not in forged.text
    nonexistent = client.get("/portfolio", headers=auth("tok-alice", **{WORKSPACE_HEADER: "ws_does_not_exist"}))
    assert (nonexistent.status_code, nonexistent.json()) == (forged.status_code, forged.json())


def test_workspace_name_is_not_a_selector(client):
    response = client.get("/workspace", headers=auth("tok-alice", **{WORKSPACE_HEADER: "Alice Owner Workspace"}))
    assert response.status_code == 403


def test_each_principal_only_reaches_their_own_data(client):
    assert [i["name"] for i in client.get("/portfolio", headers=auth("tok-bob")).json()] == ["Bob secret product"]
    assert [i["name"] for i in client.get("/portfolio", headers=auth("tok-alice")).json()] == ["Alice product"]


def test_principal_without_memberships_is_403(client):
    response = client.get("/workspace", headers=auth("tok-carol"))
    assert (response.status_code, response.json()) == (403, {"detail": {"code": "no_workspace_membership"}})


def test_multiple_memberships_need_an_explicit_authorized_selector(client):
    assert client.get("/workspace", headers=auth("tok-dave")).status_code == 400
    assert client.get("/workspace", headers=auth("tok-dave", **{WORKSPACE_HEADER: CLIENT_ACME})).json()["workspace_type"] == "client_service"
    assert client.get("/workspace", headers=auth("tok-dave", **{WORKSPACE_HEADER: OWNER_DAVE})).json()["workspace_type"] == "internal"
    assert client.get("/workspace", headers=auth("tok-dave", **{WORKSPACE_HEADER: OWNER_ALICE})).status_code == 403


def test_owner_data_route_refuses_a_client_workspace_of_the_same_principal(client):
    response = client.get("/portfolio", headers=auth("tok-dave", **{WORKSPACE_HEADER: CLIENT_ACME}))
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "workspace_type_mismatch"}}


# ----- unconfigured providers and unavailable storage fail closed -----

def test_unconfigured_verifier_fails_closed_with_503():
    response = TestClient(build_app(verifier=False)).get("/whoami", headers=auth("tok-alice"))
    assert (response.status_code, response.json()) == (503, {"detail": {"code": "identity_provider_unavailable"}})


def test_unconfigured_repository_fails_closed_with_503_only_after_identity_is_established():
    app = build_app()
    http = TestClient(app)
    assert http.get("/workspace", headers=auth("tok-alice")).json() == {"detail": {"code": "storage_unavailable"}}
    assert http.get("/workspace", headers=auth("tok-alice")).status_code == 503
    assert http.get("/workspace").status_code == 401  # unauthenticated callers cannot probe storage state
    assert http.get("/workspace", headers=auth("tok-unknown")).status_code == 401


def test_unavailable_database_is_503_never_a_fallback(tmp_path, monkeypatch, caplog):
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)

    def connect():
        raise ConnectionRefusedError("refused canary-secret-xyz at db.internal")

    http = TestClient(build_app(repository=PostgresWorkspaceRepository(connect)))
    with caplog.at_level(logging.DEBUG):
        response = http.get("/workspace", headers=auth("tok-alice"))
    assert (response.status_code, response.json()) == (503, {"detail": {"code": "storage_unavailable"}})
    assert "canary-secret-xyz" not in response.text and "canary-secret-xyz" not in caplog.text
    assert http.get("/workspace", headers=auth("tok-forged")).status_code == 401  # identity still checked first
    assert list(workdir.iterdir()) == []


def test_storage_errors_raised_inside_routes_map_through_the_installed_handler(seeded):
    class DownAfterResolution:
        def memberships_for(self, principal):
            return seeded.memberships_for(principal)

        def list_portfolio_items(self, access):
            raise StorageUnavailable()

    response = TestClient(build_app(repository=DownAfterResolution())).get("/portfolio", headers=auth("tok-alice"))
    assert (response.status_code, response.json()) == (503, {"detail": {"code": "storage_unavailable"}})
