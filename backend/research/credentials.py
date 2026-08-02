"""Staging-safe research credential loading from AWS Secrets Manager.

Only explicitly allowlisted research keys are imported into the process. The
module never returns secret values in status payloads or logs.
"""
from __future__ import annotations

import base64
import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable

RESEARCH_CREDENTIAL_KEYS = frozenset({
    "TIKTOK_ACCESS_TOKEN",
    "TIKTOK_ADVERTISER_ID",
})


@dataclass(frozen=True)
class CredentialLoadStatus:
    configured: bool
    loaded: bool
    loaded_keys: tuple[str, ...] = ()
    error_type: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "loaded": self.loaded,
            "loaded_keys": list(self.loaded_keys),
            "error_type": self.error_type,
        }


_lock = threading.Lock()
_status = CredentialLoadStatus(configured=False, loaded=False)


def _parse_secret(response: dict[str, Any]) -> dict[str, Any]:
    raw = response.get("SecretString")
    if raw is None and response.get("SecretBinary") is not None:
        binary = response["SecretBinary"]
        if isinstance(binary, str):
            binary = base64.b64decode(binary)
        raw = bytes(binary).decode("utf-8")
    if not isinstance(raw, str):
        raise ValueError("secret_payload_missing")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("secret_payload_not_object")
    return payload


def load_research_credentials(
    *,
    force: bool = False,
    client_factory: Callable[[], Any] | None = None,
) -> CredentialLoadStatus:
    """Load allowlisted research keys using the standard AWS credential chain."""
    global _status
    secret_id = os.getenv("MARKETOS_RESEARCH_SECRET_ID", "").strip()
    if not secret_id:
        with _lock:
            _status = CredentialLoadStatus(configured=False, loaded=False)
            return _status
    with _lock:
        if _status.configured and not force:
            return _status
    try:
        if client_factory is None:
            import boto3

            client = boto3.client(
                "secretsmanager",
                region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            )
        else:
            client = client_factory()
        payload = _parse_secret(client.get_secret_value(SecretId=secret_id))
        loaded_keys: list[str] = []
        for key in sorted(RESEARCH_CREDENTIAL_KEYS):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                os.environ[key] = value
                loaded_keys.append(key)
        with _lock:
            _status = CredentialLoadStatus(
                configured=True,
                loaded=True,
                loaded_keys=tuple(loaded_keys),
            )
            return _status
    except Exception as exc:  # pragma: no cover - provider-specific failures
        with _lock:
            _status = CredentialLoadStatus(
                configured=True,
                loaded=False,
                error_type=type(exc).__name__,
            )
            return _status


def credential_status() -> CredentialLoadStatus:
    with _lock:
        return _status
