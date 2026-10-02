"""Server-side principal verification seams for the FastAPI application.

This module deliberately does not implement JWT cryptography.  The selected
identity provider is an operator deployment concern; a verifier must be
injected after it has validated a token with the provider's supported SDK or
JWKS configuration.  Ordinary application imports therefore remain offline
and fail closed when no verifier is configured.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from fastapi import Depends, HTTPException, Request


class PrincipalVerificationError(ValueError):
    """The presented token is invalid or does not identify a principal."""


class PrincipalVerificationUnavailable(RuntimeError):
    """No trusted verifier is configured for this process."""


@dataclass(frozen=True)
class VerifiedPrincipal:
    """Minimal identity produced by a trusted verifier.

    Raw tokens and untrusted claims are intentionally not retained.  Workspace
    access is resolved from server-side membership records, not from a client
    supplied workspace claim or selector.
    """

    subject: str
    provider: str = "clerk"

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise PrincipalVerificationError("principal subject is required")
        if len(self.subject) > 256 or self.subject != self.subject.strip():
            raise PrincipalVerificationError("principal subject is invalid")
        if not isinstance(self.provider, str) or not self.provider or len(self.provider) > 64:
            raise PrincipalVerificationError("principal provider is invalid")


class PrincipalVerifier(Protocol):
    """Provider-specific verifier contract injected by the server boundary."""

    def verify(self, bearer_value: str) -> VerifiedPrincipal:
        """Verify a bearer token and return a sanitized principal."""


class UnconfiguredPrincipalVerifier:
    """Fail-closed default until a reviewed Clerk verifier is wired."""

    def verify(self, bearer_value: str) -> VerifiedPrincipal:
        del bearer_value
        raise PrincipalVerificationUnavailable("principal verifier is not configured")


class ClerkTokenVerifier:
    """Adapter for a trusted Clerk SDK/JWKS callback.

    ``verify_claims`` must perform signature, issuer/audience, and time claim
    validation.  Keeping that callback injected avoids a second JWT authority
    and makes fake-token tests deterministic without reading credentials.
    """

    def __init__(self, verify_claims: Any) -> None:
        if not callable(verify_claims):
            raise TypeError("verify_claims must be callable")
        self._callback = verify_claims

    def verify(self, bearer_value: str) -> VerifiedPrincipal:
        if not isinstance(bearer_value, str) or not bearer_value.strip():
            raise PrincipalVerificationError("bearer token is required")
        try:
            claims = self._callback(bearer_value)
        except PrincipalVerificationError:
            raise
        except Exception as exc:
            raise PrincipalVerificationError("bearer token could not be verified") from exc
        if not isinstance(claims, Mapping):
            raise PrincipalVerificationError("verified claims are malformed")
        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise PrincipalVerificationError("verified claims do not contain a subject")
        return VerifiedPrincipal(subject=subject, provider="clerk")


def get_principal_verifier() -> PrincipalVerifier:
    """Return the fail-closed verifier used by the default FastAPI dependency."""

    return UnconfiguredPrincipalVerifier()


def extract_bearer_token(request: Request) -> str | None:
    """Extract only a conventional bearer token, without logging its value."""

    authorization = request.headers.get("authorization", "")
    scheme, separator, bearer_value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not bearer_value.strip():
        return None
    return bearer_value.strip()


def require_verified_principal(
    request: Request,
    verifier: PrincipalVerifier = Depends(get_principal_verifier),
) -> VerifiedPrincipal:
    """FastAPI dependency mapping identity failures to safe HTTP responses."""

    bearer_value = extract_bearer_token(request)
    if bearer_value is None:
        raise HTTPException(status_code=401, detail="authentication required")
    try:
        return verifier.verify(bearer_value)
    except PrincipalVerificationUnavailable as exc:
        raise HTTPException(status_code=503, detail="authentication verifier unavailable") from exc
    except (PrincipalVerificationError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="invalid authentication") from exc


__all__ = [
    "ClerkTokenVerifier",
    "PrincipalVerificationError",
    "PrincipalVerificationUnavailable",
    "PrincipalVerifier",
    "UnconfiguredPrincipalVerifier",
    "VerifiedPrincipal",
    "extract_bearer_token",
    "get_principal_verifier",
    "require_verified_principal",
]