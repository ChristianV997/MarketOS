"""backend.identity.principal -- verified principal and token-verifier seam.

Identity is established only by a server-side verifier that returns a
``VerifiedPrincipal`` from a signed session token. Nothing a client sends
outside that token (headers, query, body, workspace ids or names) is identity.

``ClerkSessionTokenVerifier`` applies claim policy to an already
signature-verified claim set. Signature/JWKS verification is deliberately an
injected callable: no JWT/RSA library or key-fetching network call is declared
in this repository's dependencies, so none is bundled here. See
``docs/IDENTITY_WORKSPACE_FOUNDATION.md``.
"""
from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .errors import IdentityError, IdentityFoundationError

MAX_TOKEN_LENGTH = 8192
MAX_CLAIM_LENGTH = 256
MAX_LEEWAY_SECONDS = 60

_log = logging.getLogger("marketos.identity")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

SignatureVerifier = Callable[[str], Mapping[str, Any]]


def _clean_claim(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_CLAIM_LENGTH or _CONTROL_CHARS.search(value):
        raise IdentityError()
    return value


@dataclass(frozen=True)
class VerifiedPrincipal:
    """A principal whose identity was established by a token verifier."""

    issuer: str
    subject: str

    def __post_init__(self) -> None:
        _clean_claim(self.issuer)
        _clean_claim(self.subject)


class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedPrincipal:
        """Return the verified principal or raise ``IdentityError``."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


class ClerkSessionTokenVerifier:
    """Claim policy for Clerk session tokens over an injected signature check.

    ``signature_verifier(token)`` must verify the signature and expected
    algorithm against the instance's public keys and return the claims. It
    signals a bad token with ``IdentityError`` and unavailable key material
    with ``IdentityProviderUnavailable``; any other exception is treated as an
    invalid token (fail closed).

    Policy: ``iss`` must equal the configured issuer; ``exp`` is required and
    enforced; ``nbf`` is enforced when present; ``azp`` must be present and in
    the configured authorized parties (an allowlist is mandatory, matching
    Clerk's guidance that omitting it can expose CSRF); ``sub`` is required.
    """

    def __init__(
        self,
        signature_verifier: SignatureVerifier,
        *,
        issuer: str,
        authorized_parties: Iterable[str],
        leeway_seconds: float = 5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not callable(signature_verifier):
            raise TypeError("signature_verifier must be callable")
        if not isinstance(issuer, str) or not issuer:
            raise ValueError("issuer is required")
        parties = frozenset(authorized_parties)
        if not parties or not all(isinstance(p, str) and p for p in parties):
            raise ValueError("authorized_parties must be a non-empty set of non-empty strings")
        if isinstance(leeway_seconds, bool) or not 0 <= leeway_seconds <= MAX_LEEWAY_SECONDS:
            raise ValueError(f"leeway_seconds must be within 0..{MAX_LEEWAY_SECONDS}")
        self._signature_verifier = signature_verifier
        self._issuer = issuer
        self._parties = parties
        self._leeway = float(leeway_seconds)
        self._clock = clock

    def verify(self, token: str) -> VerifiedPrincipal:
        if not isinstance(token, str) or not token or len(token) > MAX_TOKEN_LENGTH:
            raise IdentityError()
        try:
            claims = self._signature_verifier(token)
        except IdentityFoundationError:
            raise
        except Exception as exc:
            _log.warning("token signature verification failed: %s", type(exc).__name__)
            raise IdentityError() from None
        if not isinstance(claims, Mapping):
            raise IdentityError()

        if claims.get("iss") != self._issuer:
            raise IdentityError()
        now = self._clock()
        exp = _number(claims.get("exp"))
        if exp is None:
            raise IdentityError()
        if now >= exp + self._leeway:
            raise IdentityError("token_expired")
        if "nbf" in claims:
            nbf = _number(claims["nbf"])
            if nbf is None or now + self._leeway < nbf:
                raise IdentityError()
        azp = claims.get("azp")
        if not isinstance(azp, str) or azp not in self._parties:
            raise IdentityError()
        return VerifiedPrincipal(issuer=self._issuer, subject=claims.get("sub"))  # type: ignore[arg-type]
