"""backend.identity.roles -- membership role policy for client-profile access.

Role ids are the TrustOS client-workspace roles (``client_viewer`` reads
client-safe material, ``internal_operator`` manages it). Anything else, including
a missing role, grants nothing.
"""
from __future__ import annotations

from collections.abc import Mapping

CLIENT_VIEWER = "client_viewer"
INTERNAL_OPERATOR = "internal_operator"
ROLES = (CLIENT_VIEWER, INTERNAL_OPERATOR)

PROFILE_READ = "client_profile:read"
PROFILE_CREATE = "client_profile:create"
PROFILE_UPDATE = "client_profile:update"
CREDENTIAL_WRITE = "setup_credential:write"

ROLE_PERMISSIONS: Mapping[str, frozenset[str]] = {
    CLIENT_VIEWER: frozenset({PROFILE_READ}),
    INTERNAL_OPERATOR: frozenset({PROFILE_READ, PROFILE_CREATE, PROFILE_UPDATE, CREDENTIAL_WRITE}),
}


def role_grants(role: object, permission: str) -> bool:
    return isinstance(role, str) and permission in ROLE_PERMISSIONS.get(role, frozenset())
