"""Server-side gate for the credential-setup mutation routes (no network, provider or real credential).

Mounts the production router with a fake verifier and the SQLite identity repository. Uses a
raw ASGI call so no HTTP client package is needed.
"""
from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi import FastAPI

from api import credentials_setup
from backend.identity.errors import IdentityError
from backend.identity.http import get_token_verifier, get_workspace_repository
from backend.identity.principal import VerifiedPrincipal
from backend.identity.roles import CLIENT_VIEWER, INTERNAL_OPERATOR

from .conftest import CAROL, CLIENT_ACME, ISSUER

CLIENT_GLOBEX = "ws_client_globex"
OPERATOR = VerifiedPrincipal(ISSUER, "user_operator")
VIEWER = VerifiedPrincipal(ISSUER, "user_viewer")
MULTI = VerifiedPrincipal(ISSUER, "user_multi")
TOKENS = {"tok-operator": OPERATOR, "tok-viewer": VIEWER, "tok-multi": MULTI, "tok-carol": CAROL}
LEAK_MARKER = "FAKE-VALUE-MUST-NOT-LEAK-123"


class FakeVerifier:
    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            return TOKENS[token]
        except KeyError:
            raise IdentityError() from None


class Resp:
    def __init__(self, status: int, body: bytes):
        self.status_code = status
        self.text = body.decode()

    def json(self):
        return json.loads(self.text)


def call(app: FastAPI, method: str, path: str, body=None, token: str | None = None) -> Resp:
    raw = b"" if body is None else json.dumps(body).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(raw)).encode())]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
        "server": ("t", 80), "client": ("c", 1), "scheme": "http", "root_path": "",
    }
    out: dict = {"status": 0, "body": b""}
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(msg):
        if msg["type"] == "http.response.start":
            out["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            out["body"] += msg.get("body", b"")

    asyncio.run(app(scope, receive, send))
    return Resp(out["status"], out["body"])


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "credentials.json"
    import backend.config as config

    monkeypatch.setattr(config, "_CONFIG_PATH", path)  # resolved at import time, so patch it
    for name in ("META_DRY_RUN", "META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
        monkeypatch.delenv(name, raising=False)
    return path


@pytest.fixture
def store(repo):
    repo.create_workspace(CLIENT_ACME, "client_service", "Acme Corp")
    repo.create_workspace(CLIENT_GLOBEX, "client_service", "Globex")
    repo.add_member(CLIENT_ACME, OPERATOR.issuer, OPERATOR.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_ACME, VIEWER.issuer, VIEWER.subject, CLIENT_VIEWER)
    repo.add_member(CLIENT_ACME, MULTI.issuer, MULTI.subject, INTERNAL_OPERATOR)
    repo.add_member(CLIENT_GLOBEX, MULTI.issuer, MULTI.subject, INTERNAL_OPERATOR)
    return repo


def make_app(repository, *, verifier=True) -> FastAPI:
    app = FastAPI()
    app.include_router(credentials_setup.router, prefix="/api/setup")
    if verifier:
        app.dependency_overrides[get_token_verifier] = lambda: FakeVerifier()
    if repository is not None:
        app.dependency_overrides[get_workspace_repository] = lambda: repository
    return app


@pytest.fixture
def app(store):
    return make_app(store)


SET = "/api/setup/credentials/set"
TEST = "/api/setup/test/meta"
GOOD = {"key": "META_ACCESS_TOKEN", "value": LEAK_MARKER}


def stored(cfg) -> dict:
    return json.loads(cfg.read_text()) if cfg.exists() else {}


@pytest.fixture
def no_provider(monkeypatch):
    from backend.integrations import meta_ads_client

    def boom(*a, **k):
        raise AssertionError("provider must never be called")

    monkeypatch.setattr(meta_ads_client, "create_campaign", boom)


# ---- authentication / identity / role ----

@pytest.mark.parametrize("token", [None, "tok-forged"])
@pytest.mark.parametrize("path,body", [(SET, GOOD), (TEST, None)])
def test_unauthenticated_is_401_and_nothing_is_written(app, cfg, no_provider, token, path, body):
    r = call(app, "POST", path, body, token)
    assert r.status_code == 401
    assert stored(cfg) == {}
    assert LEAK_MARKER not in r.text


@pytest.mark.parametrize("path,body", [(SET, GOOD), (TEST, None)])
def test_unconfigured_identity_fails_closed_503(store, cfg, no_provider, path, body):
    assert call(make_app(store, verifier=False), "POST", path, body, "tok-operator").status_code == 503
    assert call(make_app(None), "POST", path, body, "tok-operator").status_code == 503
    assert stored(cfg) == {}


@pytest.mark.parametrize("token", ["tok-viewer", "tok-carol", "tok-multi"])
@pytest.mark.parametrize("path,body", [(SET, GOOD), (TEST, None)])
def test_viewer_non_member_and_ambiguous_workspace_are_403(app, cfg, no_provider, token, path, body):
    r = call(app, "POST", path, body, token)
    assert r.status_code == 403
    assert stored(cfg) == {}
    assert LEAK_MARKER not in r.text


def test_body_cannot_select_workspace_or_role(app, cfg):
    body = dict(GOOD, workspace_id=CLIENT_ACME, role=INTERNAL_OPERATOR, approved=True)
    assert call(app, "POST", SET, body, "tok-viewer").status_code == 403
    assert stored(cfg) == {}


# ---- input validation (authorised caller) ----

@pytest.mark.parametrize(
    "key",
    ["META_DRY_RUN", "TIKTOK_DRY_RUN", "PATH", "LD_PRELOAD", "UNKNOWN_KEY", "meta_access_token", "META_ACCESS_TOKEN\n", ""],
)
def test_keys_outside_the_credential_allowlist_are_400(app, cfg, key):
    r = call(app, "POST", SET, {"key": key, "value": LEAK_MARKER}, "tok-operator")
    assert r.status_code == 400
    assert stored(cfg) == {}
    assert LEAK_MARKER not in r.text


@pytest.mark.parametrize("value", ["", "a\nb", "a\x00b", "x" * 5000], ids=["empty", "newline", "nul", "toolong"])
def test_malformed_values_are_400(app, cfg, value):
    r = call(app, "POST", SET, {"key": "META_ACCESS_TOKEN", "value": value}, "tok-operator")
    assert r.status_code == 400
    assert stored(cfg) == {}


def test_missing_or_non_string_fields_are_422(app, cfg):
    assert call(app, "POST", SET, {"key": "META_ACCESS_TOKEN"}, "tok-operator").status_code == 422
    assert call(app, "POST", SET, {"key": ["x"], "value": 1}, "tok-operator").status_code == 422
    assert stored(cfg) == {}


# ---- allowed path ----

def test_operator_can_store_an_allowlisted_credential_without_echo_or_log(app, cfg, caplog):
    with caplog.at_level(logging.DEBUG):
        r = call(app, "POST", SET, GOOD, "tok-operator")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert stored(cfg) == {"META_ACCESS_TOKEN": LEAK_MARKER}
    assert LEAK_MARKER not in r.text and LEAK_MARKER not in caplog.text


def test_storage_failure_returns_generic_500_without_exception_text(app, cfg, monkeypatch, caplog):
    import backend.config as config

    def fail(key, value):
        raise OSError(f"disk exploded with {value}")

    monkeypatch.setattr(config, "set_credential", fail)
    with caplog.at_level(logging.DEBUG):
        r = call(app, "POST", SET, GOOD, "tok-operator")
    assert r.status_code == 500
    assert LEAK_MARKER not in r.text and LEAK_MARKER not in caplog.text


# ---- provider test route ----

def test_operator_dry_run_test_is_allowed_and_offline(app, cfg, no_provider):
    r = call(app, "POST", TEST, None, "tok-operator")
    assert r.status_code == 200 and r.json()["status"] == "dry_run"


def test_live_provider_test_is_blocked_even_for_operator(app, cfg, no_provider, monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", LEAK_MARKER)
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_1")
    monkeypatch.setenv("META_DRY_RUN", "false")
    r = call(app, "POST", TEST, None, "tok-operator")
    assert r.status_code == 200
    assert r.json()["status"] == "blocked"
    assert LEAK_MARKER not in r.text


def test_unknown_service_is_404_for_operator_and_401_without_auth(app):
    assert call(app, "POST", "/api/setup/test/nope", None, "tok-operator").status_code == 404
    assert call(app, "POST", "/api/setup/test/nope", None).status_code == 401


def test_direct_callers_of_the_helper_cannot_reach_a_provider(cfg, no_provider, monkeypatch):
    """api/onboarding.py awaits the helper directly; it must be offline-only too."""
    monkeypatch.setenv("META_ACCESS_TOKEN", LEAK_MARKER)
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "act_1")
    monkeypatch.setenv("META_DRY_RUN", "false")
    result = asyncio.run(credentials_setup.run_service_test("meta"))
    assert result["status"] == "blocked"
