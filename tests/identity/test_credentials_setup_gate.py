"""Credential-setup and provider-test routes: authorization matrix, zero side effects, no provider calls.

A throwaway app mounts the production routers and the requests below are real HTTP requests driven
through the mounted app's ASGI interface (same routing, dependencies, and exception handling). The
verifier is a fake and memberships live in the identity conftest's SQLite store. Credential storage and
every provider helper are replaced by recorders, the config path is redirected into ``tmp_path``, and
the provider packages are replaced in ``sys.modules`` so real provider code can never load. Every
identity, token, value, and path below is synthetic; no network, provider, credential, or real file is
touched.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import types
import warnings
from pathlib import Path

import pytest
from fastapi import FastAPI

import backend.config as backend_config
from api import credentials_setup, onboarding
from backend.identity.errors import IdentityError, StorageUnavailable
from backend.identity.http import WORKSPACE_HEADER, get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, CREDENTIAL_TEST, CREDENTIAL_WRITE, INTERNAL_OPERATOR, role_grants

from .conftest import ISSUER

CANARY = "synthetic-canary-value-4f9a"
SENSITIVE_PATH = "/home/synthetic/.marketos/credentials.json"

OWNER_OP = "ws_owner_operator"
OWNER_OP_2 = "ws_owner_operator_two"
OWNER_VIEWER = "ws_owner_viewer"
OWNER_NOROLE = "ws_owner_norole"
CLIENT_WS = "ws_client_synthetic"

OPERATOR = VerifiedPrincipal(ISSUER, "user_operator")
VIEWER = VerifiedPrincipal(ISSUER, "user_viewer")  # internal workspace, client_viewer role
NOROLE = VerifiedPrincipal(ISSUER, "user_norole")  # internal workspace, no role
CLIENT_OP = VerifiedPrincipal(ISSUER, "user_client_operator")  # internal_operator, but only in a client workspace
CLIENT_USER = VerifiedPrincipal(ISSUER, "user_client_user")  # the client persona: client workspace, client_viewer
MULTI = VerifiedPrincipal(ISSUER, "user_multi")  # internal_operator in two internal workspaces
OUTSIDER = VerifiedPrincipal(ISSUER, "user_outsider")  # authenticated, member of nothing
TOKENS = {
    "tok-operator": OPERATOR,
    "tok-viewer": VIEWER,
    "tok-norole": NOROLE,
    "tok-clientop": CLIENT_OP,
    "tok-clientuser": CLIENT_USER,
    "tok-multi": MULTI,
    "tok-outsider": OUTSIDER,
}


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        if token == "tok-explodes":
            raise RuntimeError(f"verifier bug at {SENSITIVE_PATH}")
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


def auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer tok-{name}"}


# --------------------------------------------------------------------------- in-process ASGI client


class Response:
    def __init__(self, status_code: int, headers: dict[str, str], body: bytes, body_reads: int) -> None:
        self.status_code, self.headers, self.content, self.body_reads = status_code, headers, body, body_reads
        self.text = body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


def call(
    app: FastAPI,
    method: str,
    url: str,
    *,
    headers=None,
    json_body=None,
    content: bytes | None = None,
    chunks: list[bytes] | None = None,
    content_type: str | None = "application/json",
    declare_length: bool = True,
) -> Response:
    """Send one HTTP request to the mounted app through its ASGI interface.

    ``body_reads`` counts how many request-body messages the app consumed, so a test can prove that a
    denied caller's body was never read. ``chunks`` delivers a body in several messages (and, with
    ``declare_length=False``, without a Content-Length header).
    """
    has_body = content is not None or json_body is not None or chunks is not None
    pieces = chunks if chunks is not None else [content if content is not None else (json.dumps(json_body).encode() if json_body is not None else b"")]
    total = sum(len(piece) for piece in pieces)
    raw_headers = [(b"host", b"testserver")] + [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    if has_body and content_type:
        raw_headers.append((b"content-type", content_type.encode()))
    if declare_length:
        raw_headers.append((b"content-length", str(total).encode()))
    path, _, query = url.partition("?")
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
        "path": path, "raw_path": path.encode(), "query_string": query.encode(), "headers": raw_headers,
        "client": ("testclient", 5000), "server": ("testserver", 80), "root_path": "",
    }
    out = {"status": 500, "headers": {}, "body": b"", "reads": 0}

    async def run() -> None:
        queue = list(pieces)

        async def receive():
            if queue:
                out["reads"] += 1
                piece = queue.pop(0)
                return {"type": "http.request", "body": piece, "more_body": bool(queue)}
            return {"type": "http.disconnect"}

        async def send(message) -> None:
            if message["type"] == "http.response.start":
                out["status"] = message["status"]
                out["headers"] = {k.decode().lower(): v.decode() for k, v in message["headers"]}
            elif message["type"] == "http.response.body":
                out["body"] += message.get("body", b"")

        try:
            await app(scope, receive, send)
        except Exception:  # an unhandled server error already produced the 500 response
            pass

    asyncio.run(run())
    return Response(out["status"], out["headers"], out["body"], out["reads"])


# --------------------------------------------------------------------------- fixtures


class Effects:
    """Every side-effecting call the routes could make. Denied requests must leave this empty."""

    def __init__(self, config_path: Path) -> None:
        self.calls: list[tuple] = []
        self.stored: list[tuple[str, str]] = []
        self.live = False
        self.config_path = config_path


@pytest.fixture
def storage_effects(monkeypatch, tmp_path) -> Effects:
    """Storage and mode recorders with the config path redirected; provider packages are left alone."""
    fx = Effects(tmp_path / "credentials.json")
    monkeypatch.setattr(backend_config, "_CONFIG_PATH", fx.config_path)  # even a missed mock cannot touch a real file
    monkeypatch.setattr(backend_config, "set_credential", lambda key, value: (fx.calls.append(("storage", key)), fx.stored.append((key, value))))
    monkeypatch.setattr(backend_config, "is_dry_run", lambda service: not fx.live)
    return fx


@pytest.fixture
def effects(monkeypatch, storage_effects) -> Effects:
    """Everything in ``storage_effects`` plus recording fakes in place of every provider package."""
    fx = storage_effects

    def recorder(name, result):
        def _call(*args, **kwargs):
            fx.calls.append((name,))
            return result

        return _call

    integrations = types.ModuleType("backend.integrations")
    integrations.__path__ = []
    meta = types.ModuleType("backend.integrations.meta_ads_client")
    meta.create_campaign = recorder("meta.create_campaign", "cmp_synthetic")
    tiktok = types.ModuleType("backend.integrations.tiktok_ads")
    tiktok.create_campaign = recorder("tiktok.create_campaign", "tt_synthetic")
    creation = types.ModuleType("backend.creation")
    creation.__path__ = []
    store_builder = types.ModuleType("backend.creation.store_builder")
    store_builder.create_product_page = recorder("store_builder.product_page", {"status": "ok", "product_id": "p_synthetic"})
    integrations.meta_ads_client, integrations.tiktok_ads, creation.store_builder = meta, tiktok, store_builder
    for name, module in {
        "backend.integrations": integrations, "backend.integrations.meta_ads_client": meta,
        "backend.integrations.tiktok_ads": tiktok, "backend.creation": creation,
        "backend.creation.store_builder": store_builder,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return fx


@pytest.fixture
def store(repo):
    repo.create_workspace(OWNER_OP, "internal", "Operator Workspace")
    repo.create_workspace(OWNER_OP_2, "internal", "Second Operator Workspace")
    repo.create_workspace(OWNER_VIEWER, "internal", "Viewer Workspace")
    repo.create_workspace(OWNER_NOROLE, "internal", "No Role Workspace")
    repo.create_workspace(CLIENT_WS, "client_service", "Client Workspace")
    repo.add_member(OWNER_OP, OPERATOR.issuer, OPERATOR.subject, INTERNAL_OPERATOR)
    repo.add_member(OWNER_VIEWER, VIEWER.issuer, VIEWER.subject, CLIENT_VIEWER)
    repo.add_member(OWNER_NOROLE, NOROLE.issuer, NOROLE.subject)
    repo.add_member(CLIENT_WS, CLIENT_OP.issuer, CLIENT_OP.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_WS, CLIENT_USER.issuer, CLIENT_USER.subject, CLIENT_VIEWER)
    repo.add_member(OWNER_OP, MULTI.issuer, MULTI.subject, INTERNAL_OPERATOR)
    repo.add_member(OWNER_OP_2, MULTI.issuer, MULTI.subject, INTERNAL_OPERATOR)
    return repo


def make_app(repository, *, verifier: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(credentials_setup.router, prefix="/api/setup")
    app.include_router(onboarding.router, prefix="/api/onboarding")
    if verifier:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
    if repository is not None:
        app.dependency_overrides[get_workspace_repository] = lambda: repository
    return app


@pytest.fixture
def app(store) -> FastAPI:
    return make_app(store)


@pytest.fixture(autouse=True)
def onboarding_session():
    """One onboarding session already on the credentials step, removed afterwards."""
    onboarding._sessions["sess-synthetic"] = onboarding.OnboardingState(step=2)
    yield "sess-synthetic"
    onboarding._sessions.pop("sess-synthetic", None)


IDENTITY_DENIAL_CODES = {"missing_credentials", "invalid_credentials", "identity_provider_unavailable", "storage_unavailable"}
TARGETS = {
    "set": ("POST", "/api/setup/credentials/set", {"key": "META_ACCESS_TOKEN", "value": CANARY}),
    "test": ("POST", "/api/setup/test/meta", None),
    "onboarding": (
        "POST", "/api/onboarding/step/2/verify-credential",
        {"session_id": "sess-synthetic", "service": "meta", "credential_key": "META_ACCESS_TOKEN", "credential_value": CANARY},
    ),
}
BODY_TARGETS = ["set", "onboarding"]
SPOOF_BODY = {"actor": "admin", "user_id": "user_operator", "role": "internal_operator", "workspace_id": OWNER_OP, "is_admin": True}
SPOOF_HEADERS = {WORKSPACE_HEADER: OWNER_OP, "X-MarketOS-Role": "internal_operator", "X-Actor": "admin", "X-Forwarded-User": "user_operator"}


def send(app, target: str, *, headers=None, spoof_body: bool = False, query: str = "", **extra) -> Response:
    method, url, body = TARGETS[target]
    if spoof_body:
        body = {**(body or {}), **SPOOF_BODY}
    return call(app, method, url + query, headers=headers, json_body=body, **extra)


def assert_no_side_effects(fx: Effects) -> None:
    assert fx.calls == [] and fx.stored == []
    assert not fx.config_path.exists()


def code(response: Response) -> str:
    return response.json()["detail"]["code"]


def assert_stable(response: Response, status: int, expected_code: str, field: str | None = None) -> None:
    assert response.status_code == status, response.text
    assert response.json() == {"detail": {"code": expected_code, "field": field}}


# --------------------------------------------------------------------------- anonymous and invalid


@pytest.mark.parametrize("target", list(TARGETS))
@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer"}, {"Authorization": "Bearer tok-unknown"}, auth("explodes")],
    ids=["anonymous", "wrong-scheme", "empty-bearer", "unknown-token", "verifier-bug"],
)
def test_anonymous_and_invalid_credentials_are_401_with_no_side_effects(app, effects, target, headers):
    response = send(app, target, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert code(response) in {"missing_credentials", "invalid_credentials"}
    assert SENSITIVE_PATH not in response.text and CANARY not in response.text
    assert_no_side_effects(effects)


@pytest.mark.parametrize("target", list(TARGETS))
def test_anonymous_request_with_spoofed_identity_everywhere_is_still_401(app, effects, target):
    response = send(app, target, headers=SPOOF_HEADERS, spoof_body=True, query="?workspace_id=" + OWNER_OP + "&role=internal_operator")
    assert response.status_code == 401
    assert_no_side_effects(effects)


def test_anonymous_request_for_an_unknown_session_or_service_does_not_enumerate(app, effects):
    body = {**TARGETS["onboarding"][2], "session_id": "no-such-session"}
    assert call(app, "POST", TARGETS["onboarding"][1], json_body=body).status_code == 401
    assert call(app, "POST", "/api/setup/test/not-a-service").status_code == 401
    assert_no_side_effects(effects)


# --------------------------------------------------------------------------- the body is never read for a denied caller


DENIED_CALLERS = {
    "anonymous": ({}, 401),
    "invalid-token": (auth("unknown"), 401),
    "authenticated-without-membership": (auth("outsider"), 403),
    "client-viewer": (auth("clientuser"), 403),
}


@pytest.mark.parametrize("target", BODY_TARGETS)
@pytest.mark.parametrize("who", list(DENIED_CALLERS))
@pytest.mark.parametrize(
    "shape",
    ["oversized", "unparseable", "wrong-media-type"],
)
def test_a_denied_callers_body_is_never_read_or_parsed(app, effects, target, who, shape):
    headers, expected = DENIED_CALLERS[who]
    _, url, _ = TARGETS[target]
    kwargs = {
        "oversized": {"content": b'{"key":"' + b"x" * (1024 * 1024) + b'"}'},
        "unparseable": {"content": b"{not json " + CANARY.encode()},
        "wrong-media-type": {"content": CANARY.encode(), "content_type": "text/plain"},
    }[shape]
    response = call(app, "POST", url, headers=headers, **kwargs)
    assert response.status_code == expected  # not 413 / 415 / 422: those are decided only after authorization
    assert response.body_reads == 0
    assert CANARY not in response.text
    assert_no_side_effects(effects)


def test_unconfigured_identity_also_never_reads_the_body(store, effects):
    response = call(make_app(store, verifier=False), "POST", TARGETS["set"][1], headers=auth("operator"), content=b"x" * 4096)
    assert response.status_code == 503 and response.body_reads == 0
    assert_no_side_effects(effects)


# --------------------------------------------------------------------------- unconfigured identity


@pytest.mark.parametrize("target", list(TARGETS))
def test_unconfigured_verifier_fails_closed(store, effects, target):
    response = send(make_app(store, verifier=False), target, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "identity_provider_unavailable")
    assert_no_side_effects(effects)


@pytest.mark.parametrize("target", list(TARGETS))
def test_unconfigured_repository_fails_closed(effects, target):
    response = send(make_app(None), target, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "storage_unavailable")
    assert_no_side_effects(effects)


@pytest.mark.parametrize("failure", [StorageUnavailable(), RuntimeError(f"driver exploded near hunter2 {SENSITIVE_PATH}")])
@pytest.mark.parametrize("target", list(TARGETS))
def test_membership_lookup_outage_is_503_without_detail(effects, target, failure):
    class Down:
        def memberships_for(self, principal):
            raise failure

    response = send(make_app(Down()), target, headers=auth("operator"))
    assert (response.status_code, code(response)) == (503, "storage_unavailable")
    assert "hunter2" not in response.text and SENSITIVE_PATH not in response.text
    assert_no_side_effects(effects)


# --------------------------------------------------------------------------- unauthorized and spoofed


UNAUTHORIZED = {
    "authenticated-no-membership": auth("outsider"),
    "viewer-role-in-an-internal-workspace": auth("viewer"),
    "membership-without-role": auth("norole"),
    "operator-in-a-client-workspace-only": auth("clientop"),
    "client-user-in-a-client-workspace": auth("clientuser"),
    "operator-in-two-internal-workspaces": auth("multi"),
}


@pytest.mark.parametrize("target", list(TARGETS))
@pytest.mark.parametrize("who", list(UNAUTHORIZED))
@pytest.mark.parametrize("spoofed", [False, True], ids=["plain", "spoofed"])
def test_authenticated_but_unauthorized_callers_are_403_with_no_side_effects(app, effects, target, who, spoofed):
    headers = {**UNAUTHORIZED[who], **(SPOOF_HEADERS if spoofed else {})}
    response = send(app, target, headers=headers, spoof_body=spoofed, query=("?workspace_id=" + OWNER_OP) if spoofed else "")
    assert response.status_code == 403
    assert code(response) in {"workspace_not_authorized", "role_not_authorized", "no_workspace_membership", "workspace_ambiguous"}
    assert OWNER_OP not in response.text and CANARY not in response.text
    assert response.body_reads == 0
    assert_no_side_effects(effects)


def test_a_body_or_header_cannot_grant_the_role_or_workspace(app, effects):
    response = send(app, "set", headers={**auth("viewer"), **SPOOF_HEADERS}, spoof_body=True)
    assert response.status_code == 403 and code(response) == "role_not_authorized"
    assert_no_side_effects(effects)


def test_a_workspace_selector_cannot_resolve_an_ambiguous_membership(app, effects):
    response = send(app, "set", headers={**auth("multi"), WORKSPACE_HEADER: OWNER_OP})
    assert response.status_code == 403 and code(response) == "workspace_ambiguous"
    assert_no_side_effects(effects)


# --------------------------------------------------------------------------- authorized (synthetic operator)


def test_operator_can_store_an_allowlisted_credential_without_echo_or_log(app, effects, caplog):
    with caplog.at_level(logging.DEBUG):
        response = send(app, "set", headers=auth("operator"))
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert response.headers["cache-control"] == "no-store"
    assert effects.stored == [("META_ACCESS_TOKEN", CANARY)]
    assert effects.calls == [("storage", "META_ACCESS_TOKEN")]  # no provider helper
    assert CANARY not in response.text and CANARY not in caplog.text


@pytest.mark.parametrize("field", sorted({*SPOOF_BODY, "Workspace-ID", "TENANT_ID", " role "}))
def test_a_caller_or_workspace_field_in_the_body_is_rejected_even_for_an_operator(app, effects, field):
    body = {**TARGETS["set"][2], field: "internal_operator"}
    response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body=body)
    assert_stable(response, 422, "identity_field_rejected")
    assert_no_side_effects(effects)


# --------------------------------------------------------------------------- authorized: the request body contract


def _post(app, target, **kwargs) -> Response:
    return call(app, "POST", TARGETS[target][1], headers=auth("operator"), **kwargs)


@pytest.mark.parametrize("target", BODY_TARGETS)
def test_non_json_media_type_is_415(app, effects, target):
    response = _post(app, target, content=json.dumps(TARGETS[target][2]).encode(), content_type="text/plain")
    assert_stable(response, 415, "unsupported_media_type")
    assert_no_side_effects(effects)


@pytest.mark.parametrize("target", BODY_TARGETS)
def test_oversized_body_is_413_whether_or_not_the_length_is_declared(app, effects, target):
    big = credentials_setup.MAX_BODY_BYTES + 1
    declared = _post(app, target, content=b" " * big)
    assert_stable(declared, 413, "payload_too_large")
    streamed = _post(app, target, chunks=[b" " * 9000, b" " * 9000], declare_length=False)
    assert_stable(streamed, 413, "payload_too_large")
    assert_no_side_effects(effects)


@pytest.mark.parametrize("target", BODY_TARGETS)
def test_a_body_exactly_at_the_cap_is_parsed_not_rejected_for_size(app, effects, target):
    padding = credentials_setup.MAX_BODY_BYTES - len(b'{"x":""}')
    response = _post(app, target, content=b'{"x":"' + b"a" * padding + b'"}')
    assert response.status_code == 422 and code(response) == "unknown_field"  # parsed, then rejected on content
    assert_no_side_effects(effects)


@pytest.mark.parametrize(
    "content, expected",
    [(b"{not json", "invalid_json"), (b"", "invalid_json"), (b"\xff\xfe", "invalid_json"), (b"[]", "invalid_body"), (b'"text"', "invalid_body"), (b"null", "invalid_body")],
)
@pytest.mark.parametrize("target", BODY_TARGETS)
def test_unparseable_or_non_object_bodies_are_stable_422s(app, effects, target, content, expected):
    response = _post(app, target, content=content, content_type="application/json")
    assert_stable(response, 422, expected)
    assert_no_side_effects(effects)


def test_unknown_fields_are_rejected_without_naming_them(app, effects):
    body = {**TARGETS["set"][2], CANARY: "x"}
    response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body=body)
    assert_stable(response, 422, "unknown_field")
    assert CANARY not in response.text
    assert_no_side_effects(effects)


@pytest.mark.parametrize("missing", ["key", "value"])
def test_a_missing_field_is_a_stable_422_naming_only_the_field(app, effects, missing):
    body = {k: v for k, v in TARGETS["set"][2].items() if k != missing}
    response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body=body)
    assert_stable(response, 422, "missing_field", missing)
    assert_no_side_effects(effects)


@pytest.mark.parametrize(
    "value",
    [12345678, True, None, [CANARY], {"nested": CANARY}, 1.5],
    ids=["int", "bool", "null", "list", "object", "float"],
)
def test_a_mistyped_value_is_a_stable_422_that_does_not_echo_the_submitted_value(app, effects, value, caplog):
    body = {"key": "META_ACCESS_TOKEN", "value": value}
    with caplog.at_level(logging.DEBUG):
        response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body=body)
    assert_stable(response, 422, "invalid_type", "value")
    assert CANARY not in response.text and "12345678" not in response.text and CANARY not in caplog.text
    assert_no_side_effects(effects)


@pytest.mark.parametrize("key", ["META_DRY_RUN", "TIKTOK_DRY_RUN", "meta_access_token", "PATH", "", "META_ACCESS_TOKEN\n", "__proto__"])
def test_keys_outside_the_provider_allowlist_are_400_and_not_stored(app, effects, key):
    response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body={"key": key, "value": "v"})
    assert_stable(response, 400, "unsupported_key", "key")
    assert_no_side_effects(effects)


@pytest.mark.parametrize("value", ["", "x" * 4097, "a\nb", "a\rb", "a\x00b", "a\x7fb"])
def test_malformed_values_are_400_and_not_stored(app, effects, value):
    response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body={"key": "META_ACCESS_TOKEN", "value": value})
    assert_stable(response, 400, "invalid_value", "value")
    assert_no_side_effects(effects)


def test_a_value_at_the_length_limit_is_accepted(app, effects):
    response = call(app, "POST", TARGETS["set"][1], headers=auth("operator"), json_body={"key": "META_ACCESS_TOKEN", "value": "v" * 4096})
    assert response.status_code == 200
    assert effects.stored == [("META_ACCESS_TOKEN", "v" * 4096)]


def test_storage_failure_is_a_stable_500_that_reflects_and_logs_nothing_sensitive(app, effects, monkeypatch, caplog):
    def boom(key, value):
        raise RuntimeError(f"cannot write {SENSITIVE_PATH} for {CANARY}")

    monkeypatch.setattr(backend_config, "set_credential", boom)
    with caplog.at_level(logging.DEBUG):
        response = send(app, "set", headers=auth("operator"))
    assert_stable(response, 500, "credential_store_failed")
    for leaked in (CANARY, SENSITIVE_PATH):
        assert leaked not in response.text and leaked not in caplog.text


# --------------------------------------------------------------------------- provider test route


@pytest.mark.parametrize("service", ["meta", "tiktok", "shopify", "META"])
def test_provider_test_in_dry_run_reports_dry_run_and_calls_no_provider(app, effects, service):
    response = call(app, "POST", f"/api/setup/test/{service}", headers=auth("operator"))
    assert response.status_code == 200 and response.json()["status"] == "dry_run"
    assert response.headers["cache-control"] == "no-store"
    assert effects.calls == []


@pytest.mark.parametrize("service", ["meta", "tiktok", "shopify"])
def test_provider_test_in_live_mode_is_blocked_and_never_reaches_a_mutating_helper(app, effects, service):
    effects.live = True
    response = call(app, "POST", f"/api/setup/test/{service}", headers=auth("operator"))
    assert response.status_code == 200 and response.json()["status"] == "blocked"
    assert "campaign_id" not in response.json() and "product_id" not in response.json()
    assert effects.calls == []  # create_campaign / create_product_page were never called


def test_provider_test_never_reads_a_request_body(app, effects):
    response = call(app, "POST", "/api/setup/test/meta", headers=auth("operator"), json_body={**SPOOF_BODY, "value": CANARY})
    assert response.status_code == 200 and response.body_reads == 0
    assert CANARY not in response.text
    assert_no_side_effects(effects)


@pytest.mark.parametrize("service", ["unknown", "meta%2F..", "%3Cscript%3Ealert(1)%3C%2Fscript%3E", "stripe"])
def test_unknown_service_is_a_stable_404_that_does_not_echo_the_input(app, effects, service):
    response = call(app, "POST", f"/api/setup/test/{service}", headers=auth("operator"))
    assert_stable(response, 404, "unknown_service", "service")
    assert effects.calls == []


def test_provider_status_failure_is_generic(app, effects, monkeypatch):
    def boom(service):
        raise RuntimeError(f"config unreadable {SENSITIVE_PATH}")

    monkeypatch.setattr(backend_config, "is_dry_run", boom)
    response = call(app, "POST", "/api/setup/test/meta", headers=auth("operator"))
    assert response.json() == {"status": "error", "message": "Provider status unavailable"}
    assert effects.calls == []


# --------------------------------------------------------------------------- onboarding verify route


def test_onboarding_verify_stores_once_reports_mode_and_calls_no_provider(app, effects, onboarding_session):
    effects.live = True
    response = send(app, "onboarding", headers=auth("operator"))
    assert response.status_code == 200
    assert response.json()["test_result"]["status"] == "blocked" and CANARY not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert effects.stored == [("META_ACCESS_TOKEN", CANARY)]
    assert effects.calls == [("storage", "META_ACCESS_TOKEN")]
    assert onboarding._sessions[onboarding_session].credentials_set == {"meta": "blocked"}


def test_onboarding_verify_rejects_a_non_provider_key_or_unknown_service_before_storing(app, effects):
    method, url, body = TARGETS["onboarding"]
    for patch, status in (({"credential_key": "META_DRY_RUN"}, 400), ({"service": "unknown"}, 404), ({"credential_value": "a\nb"}, 400)):
        assert call(app, method, url, headers=auth("operator"), json_body={**body, **patch}).status_code == status
    assert_no_side_effects(effects)


def test_onboarding_verify_rejects_caller_fields_and_mistyped_values_without_echo(app, effects):
    method, url, body = TARGETS["onboarding"]
    assert_stable(call(app, method, url, headers=auth("operator"), json_body={**body, "user_id": "u"}), 422, "identity_field_rejected")
    mistyped = call(app, method, url, headers=auth("operator"), json_body={**body, "credential_value": [CANARY]})
    assert_stable(mistyped, 422, "invalid_type", "credential_value")
    assert CANARY not in mistyped.text
    assert_no_side_effects(effects)


def test_onboarding_verify_unknown_session_is_404_only_for_an_authorized_caller(app, effects):
    method, url, body = TARGETS["onboarding"]
    response = call(app, method, url, headers=auth("operator"), json_body={**body, "session_id": "no-such-session"})
    assert response.status_code == 404
    assert_no_side_effects(effects)


def test_onboarding_storage_failure_is_generic(app, effects, monkeypatch, caplog):
    monkeypatch.setattr(backend_config, "set_credential", lambda key, value: (_ for _ in ()).throw(RuntimeError(f"{SENSITIVE_PATH} {CANARY}")))
    with caplog.at_level(logging.DEBUG):
        response = send(app, "onboarding", headers=auth("operator"))
    assert_stable(response, 400, "credential_store_failed")
    for leaked in (CANARY, SENSITIVE_PATH):
        assert leaked not in response.text and leaked not in caplog.text


# --------------------------------------------------------------------------- structure, read routes, production mount


def test_roles_grant_the_credential_permissions_to_operators_only():
    for permission in (CREDENTIAL_WRITE, CREDENTIAL_TEST):
        assert role_grants(INTERNAL_OPERATOR, permission)
        assert not role_grants(CLIENT_VIEWER, permission)
        assert not role_grants(None, permission) and not role_grants("admin", permission)


def _dependency_calls(dependant) -> set:
    found = set()
    for sub in dependant.dependencies:
        found.add(sub.call)
        found |= _dependency_calls(sub)
    return found


def test_every_mutating_or_probing_route_depends_on_a_gate():
    """Structural guard: removing a gate from one of these routes must fail a test, not only a request."""
    gated = {
        ("/credentials/set", "POST"): {credentials_setup.credential_write_gate},
        ("/test/{service}", "POST"): {credentials_setup.credential_test_gate},
    }
    seen = set()
    for route in credentials_setup.router.routes:
        for method in route.methods - {"HEAD", "OPTIONS"}:
            if method != "GET":
                assert (route.path, method) in gated, f"unreviewed non-GET route {method} {route.path}"
                assert gated[(route.path, method)] <= _dependency_calls(route.dependant)
                seen.add((route.path, method))
    assert seen == set(gated)
    verify = next(r for r in onboarding.router.routes if r.path == "/step/2/verify-credential")
    assert {credentials_setup.credential_write_gate, credentials_setup.credential_test_gate} <= _dependency_calls(verify.dependant)


def test_read_routes_error_bodies_are_stable_and_reflect_nothing(app, effects, monkeypatch, caplog):
    def boom():
        raise RuntimeError(f"unreadable {SENSITIVE_PATH} {CANARY}")

    monkeypatch.setattr(backend_config, "list_configured_services", boom)
    with caplog.at_level(logging.DEBUG):
        status = call(app, "GET", "/api/setup/credentials/status")
        unknown = call(app, "GET", f"/api/setup/instructions/{CANARY}")
    assert_stable(status, 500, "status_unavailable")
    assert_stable(unknown, 404, "unknown_service", "service")
    for leaked in (CANARY, SENSITIVE_PATH):
        assert leaked not in status.text + unknown.text and leaked not in caplog.text


def test_production_app_denies_both_routes_and_logs_no_request_content(storage_effects, caplog):
    """The real application: with no verifier or repository wired, even a well-formed token is refused.

    The assertion is denial (401/503), not a specific code, so it stays true once deployment wiring lands
    and a real verifier rejects this synthetic token with 401.
    """
    from backend.api import app as production_app

    with caplog.at_level(logging.DEBUG):
        for target in ("set", "test"):
            for headers in ({}, auth("operator"), {"Authorization": f"Bearer {CANARY}"}):
                response = send(production_app, target, headers=headers)
                assert response.status_code in {401, 503}, (target, headers)
                assert code(response) in IDENTITY_DENIAL_CODES, response.text  # the identity gate answered, nothing else
                assert CANARY not in response.text
    assert CANARY not in caplog.text  # request logging records route summaries, never bodies or headers
    assert_no_side_effects(storage_effects)


def _mounted_mutating_operations(application, prefixes):
    """(METHOD, path) for every non-read operation the application publishes under ``prefixes``.

    Read from the application's OpenAPI document rather than its router internals, which differ across FastAPI versions.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # unrelated routes in the app trigger duplicate-operation-id warnings
        paths = application.openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith(prefixes)
        for method in operations
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    )


def test_every_mutating_operation_the_production_app_mounts_under_setup_or_onboarding_denies_an_anonymous_caller(storage_effects):
    """Tripwire on the real mounted app: a new or newly mounted write route that lacks a gate answers something other than an identity denial."""
    from backend.api import app as production_app

    operations = _mounted_mutating_operations(production_app, ("/api/setup", "/api/onboarding"))
    assert ("POST", "/api/setup/credentials/set") in operations and ("POST", "/api/setup/test/{service}") in operations
    for method, path in operations:
        concrete = re.sub(r"\{[^}]+\}", "meta", path)
        response = call(production_app, method, concrete, json_body={"key": "META_ACCESS_TOKEN", "value": CANARY})
        assert response.status_code in {401, 503} and code(response) in IDENTITY_DENIAL_CODES, f"{method} {path} is not behind an identity gate"
    assert_no_side_effects(storage_effects)
