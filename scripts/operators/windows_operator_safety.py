"""Path, secret, and live-flag guards for the Windows operator workflow.

This module does not import ``evaluation`` (scipy-gated on some machines).
It never grants launch, ads, order, payment, or messaging authority.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

FORBIDDEN_OUTPUT_SEGMENTS = ("artifacts", ".git", ".env", "credentials", "secrets", "node_modules")
ALLOWED_INPUT_SUFFIXES = {".json", ".csv", ".md"}
SECRET_KEY_NAMES = frozenset({
    "api_key", "apikey", "access_token", "authorization", "auth_token",
    "password", "private_key", "secret", "secret_key", "token", "credential",
    "cookie", "cookies", "cj_api_key",
})
SECRET_SHAPED = re.compile(
    r"(?is)("
    r"-----begin (?:rsa |ec |dsa |openssh )?private key-----"
    r"|ghp_[A-Za-z0-9_]{20,}"
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-(?:live|test)?-?[A-Za-z0-9]{16,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|bearer [A-Za-z0-9._-]{10,}"
    r")"
)
LIVE_FLAG_TOKENS = frozenset({
    "allow-network",
    "allow-public-network",
    "write-supabase",
    "use-live-provider",
    "use-model-inference",
    "claim-live-execution",
    "live-validated",
    "allow-start",
})
AUTHORITY_KEYS = ("launch", "ads", "orders", "payments", "messaging", "publishing", "inventory")


class OperatorSafetyError(ValueError):
    def __init__(self, message: str, exit_code: int = 2) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def contains_secret_shaped(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_l = str(key).lower().replace("-", "_")
            if key_l in SECRET_KEY_NAMES or contains_secret_shaped(item):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(contains_secret_shaped(item) for item in value)
    if isinstance(value, str):
        return bool(SECRET_SHAPED.search(value))
    return False


def reject_live_flags(argv: list[str]) -> None:
    normalized = [item.lstrip("-").lower() for item in argv]
    for token in LIVE_FLAG_TOKENS:
        if token in normalized:
            raise OperatorSafetyError(f"blocked live/network/provider flag: --{token}", 4)


def resolve_under_root(root: Path, value: str) -> Path:
    if ".." in Path(value).parts or ".." in value.replace("\\", "/"):
        raise OperatorSafetyError("path traversal is not allowed")
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    return resolved


def require_safe_input(root: Path, value: str, *, label: str) -> Path:
    resolved = resolve_under_root(root, value)
    if not resolved.exists():
        raise OperatorSafetyError(f"{label} does not exist: {resolved}")
    if resolved.suffix.lower() not in ALLOWED_INPUT_SUFFIXES:
        raise OperatorSafetyError(f"{label} must be .json, .csv, or .md: {resolved}")
    return resolved


def require_safe_output_dir(root: Path, value: str) -> Path:
    resolved = resolve_under_root(root, value)
    text = str(resolved).replace("\\", "/")
    for segment in FORBIDDEN_OUTPUT_SEGMENTS:
        if re.search(rf"(^|/){re.escape(segment)}(/|$)", text, re.I):
            raise OperatorSafetyError(f"output path resolves into forbidden location: {segment}")
    artifacts = (root / "artifacts").resolve()
    try:
        resolved.relative_to(artifacts)
        raise OperatorSafetyError("writing into artifacts/ is not allowed")
    except ValueError:
        if str(resolved).startswith(str(artifacts)):
            raise OperatorSafetyError("writing into artifacts/ is not allowed") from None
    return resolved


def load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise OperatorSafetyError(f"JSON object required: {path}")
    if contains_secret_shaped(payload):
        raise OperatorSafetyError(f"secret-shaped content rejected: {path}", 4)
    return payload


def assert_no_authority(payload: dict[str, Any]) -> None:
    authorities = payload.get("authorities") or payload.get("authority") or {}
    if not isinstance(authorities, dict):
        return
    for key in AUTHORITY_KEYS:
        if authorities.get(key) is True:
            raise OperatorSafetyError(f"operator packet must not grant {key} authority", 4)
