"""Claim policy of ClerkSessionTokenVerifier over an injected (fake) signature check."""
from __future__ import annotations

import logging
import math

import pytest

from backend.identity.errors import IdentityError, IdentityProviderUnavailable
from backend.identity.principal import MAX_TOKEN_LENGTH, ClerkSessionTokenVerifier, VerifiedPrincipal

ISSUER = "https://clerk.test"
PARTY = "https://app.marketos.test"
NOW = 1_800_000_000.0
_MISSING = object()


def claims(**overrides):
    base = {"iss": ISSUER, "sub": "user_alice", "azp": PARTY, "exp": NOW + 60, "nbf": NOW - 5, "iat": NOW - 5}
    for key, value in overrides.items():
        if value is _MISSING:
            base.pop(key, None)
        else:
            base[key] = value
    return base


def verifier(signature_verifier=None, **kwargs):
    kwargs.setdefault("issuer", ISSUER)
    kwargs.setdefault("authorized_parties", [PARTY])
    return ClerkSessionTokenVerifier(signature_verifier or (lambda token: claims()), clock=lambda: NOW, **kwargs)


def test_valid_claims_yield_the_verified_principal():
    seen = []

    def signature_verifier(token):
        seen.append(token)
        return claims()

    principal = verifier(signature_verifier).verify("tok-alice")
    assert principal == VerifiedPrincipal(ISSUER, "user_alice")
    assert seen == ["tok-alice"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://evil.test"},
        {"iss": _MISSING},
        {"exp": _MISSING},
        {"exp": "1800000060"},
        {"exp": True},
        {"exp": math.nan},
        {"exp": math.inf},
        {"exp": 10**400},
        {"nbf": 10**400},
        {"nbf": NOW + 30},
        {"nbf": "soon"},
        {"azp": _MISSING},
        {"azp": "https://evil.test"},
        {"azp": 7},
        {"sub": _MISSING},
        {"sub": ""},
        {"sub": 42},
        {"sub": "x" * 257},
        {"sub": "user\nalice"},
    ],
)
def test_invalid_claims_are_401_invalid_credentials(overrides):
    with pytest.raises(IdentityError) as caught:
        verifier(lambda token: claims(**overrides)).verify("tok-alice")
    assert caught.value.status_code == 401
    assert caught.value.code == "invalid_credentials"


def test_expiry_is_enforced_with_bounded_leeway():
    assert verifier(lambda t: claims(exp=NOW - 3)).verify("tok").subject == "user_alice"
    with pytest.raises(IdentityError) as caught:
        verifier(lambda t: claims(exp=NOW - 5)).verify("tok")
    assert caught.value.code == "token_expired"
    assert verifier(lambda t: claims(nbf=NOW + 4)).verify("tok").subject == "user_alice"


def test_nbf_is_optional_but_exp_is_not():
    assert verifier(lambda t: claims(nbf=_MISSING)).verify("tok").subject == "user_alice"
    with pytest.raises(IdentityError):
        verifier(lambda t: claims(exp=_MISSING)).verify("tok")


def test_signature_failures_fail_closed_without_leaking_detail(caplog):
    secret_token = "tok-secret-value-123"

    def exploding(token):
        raise ValueError(f"bad signature for {token}")

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(IdentityError) as caught:
            verifier(exploding).verify(secret_token)
    assert caught.value.code == "invalid_credentials"
    assert caught.value.__cause__ is None
    assert secret_token not in str(caught.value)
    assert secret_token not in caplog.text
    assert "ValueError" in caplog.text


def test_identity_and_availability_errors_from_the_signature_check_propagate():
    def rejected(token):
        raise IdentityError()

    def unavailable(token):
        raise IdentityProviderUnavailable()

    with pytest.raises(IdentityError):
        verifier(rejected).verify("tok")
    with pytest.raises(IdentityProviderUnavailable) as caught:
        verifier(unavailable).verify("tok")
    assert caught.value.status_code == 503


@pytest.mark.parametrize("bad_claims", [None, [], "claims", 3])
def test_non_mapping_claims_are_rejected(bad_claims):
    with pytest.raises(IdentityError):
        verifier(lambda t: bad_claims).verify("tok")


@pytest.mark.parametrize("token", ["", None, 5, "t" * (MAX_TOKEN_LENGTH + 1)])
def test_unusable_tokens_never_reach_the_signature_check(token):
    calls = []
    with pytest.raises(IdentityError):
        verifier(lambda t: calls.append(t) or claims()).verify(token)
    assert calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"authorized_parties": []},
        {"authorized_parties": [""]},
        {"issuer": ""},
        {"leeway_seconds": -1},
        {"leeway_seconds": 61},
        {"leeway_seconds": True},
    ],
)
def test_misconfiguration_is_rejected_at_construction(kwargs):
    with pytest.raises(ValueError):
        verifier(**kwargs)


def test_signature_verifier_must_be_callable():
    with pytest.raises(TypeError):
        ClerkSessionTokenVerifier("not-callable", issuer=ISSUER, authorized_parties=[PARTY])  # type: ignore[arg-type]


def test_principal_rejects_empty_or_control_character_claims():
    with pytest.raises(IdentityError):
        VerifiedPrincipal("", "user")
    with pytest.raises(IdentityError):
        VerifiedPrincipal(ISSUER, "user\x00")
