"""backend.identity.repository -- Postgres-targeted durable store (DB-API 2.0).

Owns principal->workspace membership, the owner portfolio, and operator-managed
client profiles. Design constraints:

* The caller injects ``connect`` (a zero-arg callable returning a DB-API
  connection, e.g. a psycopg connection factory). There is no default, no file
  fallback, and no environment/credential handling here.
* SQL is written once with ``?`` placeholders and translated to ``%s`` for
  ``paramstyle="format"`` (psycopg). Tests exercise the identical SQL on SQLite
  (``paramstyle="qmark"``); it has not been run against a Postgres server here.
* Every data method re-verifies membership and workspace type from the database
  for the ``WorkspaceAccess`` it is handed, so a forged or stale access object
  cannot reach another workspace's rows.
* Nothing is written to the JSON ``WorkspaceRegistry`` (no write-through).
"""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar

from .errors import (
    IdentityFoundationError,
    ProfileNotFound,
    StorageConflict,
    StorageUnavailable,
    WorkspaceAccessDenied,
)
from .principal import VerifiedPrincipal
from .roles import ROLES, role_grants
from .workspaces import WORKSPACE_ID_PATTERN, WorkspaceAccess

OWNER_TYPE = "internal"
CLIENT_TYPE = "client_service"
WORKSPACE_TYPES = (OWNER_TYPE, CLIENT_TYPE)
EVIDENCE_LABELS = ("fixture", "manual", "assumption", "derived", "unavailable")
BUSINESS_TYPES = ("service_b2c", "service_b2b", "product", "other")
ENTRY_KINDS = ("segment", "target_market", "offering", "social_account")

_log = logging.getLogger("marketos.identity")
_T = TypeVar("_T")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

_UNAVAILABLE_ERRORS = frozenset({"OperationalError", "InterfaceError", "InternalError", "ProgrammingError"})
_CONFLICT_ERRORS = frozenset({"IntegrityError"})

_SQL = {
    "workspace_insert": "INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)",
    "identity_insert": "INSERT INTO workspace_identity (workspace_id, workspace_type, created_at) VALUES (?, ?, ?)",
    "member_insert": (
        "INSERT INTO workspace_members (issuer, subject, workspace_id, role, created_at) VALUES (?, ?, ?, ?, ?)"
    ),
    "memberships": (
        "SELECT m.workspace_id, i.workspace_type, w.name, m.role FROM workspace_members m "
        "JOIN workspace_identity i ON i.workspace_id = m.workspace_id "
        "JOIN workspaces w ON w.workspace_id = m.workspace_id "
        "WHERE m.issuer = ? AND m.subject = ? ORDER BY m.workspace_id"
    ),
    "member_type": (
        "SELECT i.workspace_type, m.role FROM workspace_members m "
        "JOIN workspace_identity i ON i.workspace_id = m.workspace_id "
        "WHERE m.issuer = ? AND m.subject = ? AND m.workspace_id = ?"
    ),
    "item_insert": (
        "INSERT INTO owner_portfolio_items "
        "(item_id, workspace_id, name, category, segment, evidence_label, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    ),
    "item_list": (
        "SELECT item_id, workspace_id, name, category, segment, evidence_label "
        "FROM owner_portfolio_items WHERE workspace_id = ? ORDER BY created_at, item_id"
    ),
    "profile_upsert": (
        "INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT (workspace_id) DO UPDATE SET "
        "company_name = excluded.company_name, business_type = excluded.business_type, "
        "updated_at = excluded.updated_at"
    ),
    "profile_insert": (
        "INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?)"
    ),
    "profile_update": (
        "UPDATE client_profiles SET company_name = ?, business_type = ?, updated_at = ? WHERE workspace_id = ?"
    ),
    "entry_delete_kind": "DELETE FROM client_profile_entries WHERE workspace_id = ? AND kind = ?",
    "profile_get": "SELECT workspace_id, company_name, business_type FROM client_profiles WHERE workspace_id = ?",
    "entry_insert": (
        "INSERT INTO client_profile_entries (entry_id, workspace_id, kind, label, platform, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    ),
    "entry_list": (
        "SELECT entry_id, kind, label, platform, connection_state FROM client_profile_entries "
        "WHERE workspace_id = ? ORDER BY created_at, entry_id"
    ),
}


@dataclass(frozen=True)
class PortfolioItem:
    item_id: str
    workspace_id: str
    name: str
    category: str | None
    segment: str | None
    evidence_label: str


@dataclass(frozen=True)
class ProfileEntry:
    entry_id: str
    kind: str
    label: str
    platform: str | None
    connection_state: str


@dataclass(frozen=True)
class ClientProfile:
    workspace_id: str
    company_name: str
    business_type: str
    entries: tuple[ProfileEntry, ...] = ()


EntryInput = tuple[str, str, "str | None"]  # (kind, label, platform)


def _clean_entries(entries: Sequence[EntryInput]) -> tuple[EntryInput, ...]:
    cleaned: list[EntryInput] = []
    for kind, label, platform in entries:
        _choice(kind, "kind", ENTRY_KINDS)
        label = _text(label, "label")
        if kind == "social_account":
            platform = _text(platform, "platform", max_len=64)
        elif platform is not None:
            raise ValueError("platform is only valid for social_account entries")
        cleaned.append((kind, label, platform))
    if len({(k, label, p or "") for k, label, p in cleaned}) != len(cleaned):
        raise ValueError("duplicate entries")
    return tuple(cleaned)


def new_workspace_id() -> str:
    """Random, non-guessable workspace id (never derived from a name)."""
    return f"ws_{uuid.uuid4().hex}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(value: Any, field: str, *, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or _CONTROL_CHARS.search(cleaned):
        raise ValueError(f"{field} is invalid")
    return cleaned


def _identity_key(value: Any, field: str) -> str:
    """Identity keys are matched exactly, so padded values are rejected, never normalized."""
    if not isinstance(value, str) or value != value.strip():
        raise ValueError(f"{field} is invalid")
    return _text(value, field, max_len=256)


def _optional_text(value: Any, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _choice(value: Any, field: str, allowed: Sequence[str]) -> str:
    if value not in allowed:
        raise ValueError(f"{field} must be one of {', '.join(allowed)}")
    return value


def _exception_names(exc: BaseException) -> set[str]:
    return {cls.__name__ for cls in type(exc).__mro__}


class PostgresWorkspaceRepository:
    def __init__(
        self,
        connect: Callable[[], Any],
        *,
        paramstyle: str = "format",
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        if not callable(connect):
            raise TypeError("connect must be a callable returning a DB-API connection")
        if paramstyle not in {"format", "qmark"}:
            raise ValueError("paramstyle must be 'format' (psycopg) or 'qmark'")
        self._connect = connect
        self._paramstyle = paramstyle
        self._clock = clock

    def _q(self, key: str) -> str:
        sql = _SQL[key]
        return sql.replace("?", "%s") if self._paramstyle == "format" else sql

    def _run(self, operation: Callable[[Any], _T], *, write: bool = False) -> _T:
        try:
            connection = self._connect()
        except Exception as exc:
            _log.warning("storage connect failed: %s", type(exc).__name__)
            raise StorageUnavailable() from None
        try:
            cursor = connection.cursor()
            try:
                result = operation(cursor)
            finally:
                _quietly(cursor.close)
            if write:
                connection.commit()
            return result
        except IdentityFoundationError:
            _quietly(connection.rollback)
            raise
        except Exception as exc:
            _quietly(connection.rollback)
            names = _exception_names(exc)
            if names & _CONFLICT_ERRORS:
                raise StorageConflict() from None
            if names & _UNAVAILABLE_ERRORS:
                _log.warning("storage operation failed: %s", type(exc).__name__)
                raise StorageUnavailable() from None
            raise
        finally:
            _quietly(connection.close)

    def _require_access(
        self, cursor: Any, access: WorkspaceAccess, expected_type: str, permission: str | None = None
    ) -> None:
        cursor.execute(self._q("member_type"), (access.issuer, access.subject, access.workspace_id))
        row = cursor.fetchone()
        if row is None:
            raise WorkspaceAccessDenied()
        if row[0] != expected_type:
            raise WorkspaceAccessDenied("workspace_type_mismatch")
        # The stored role is authoritative; the role carried on ``access`` is never trusted.
        if permission is not None and not role_grants(row[1], permission):
            raise WorkspaceAccessDenied("role_not_authorized")

    # -- provisioning (operator/bootstrap; deliberately not exposed by any route) --

    def create_workspace(self, workspace_id: str, workspace_type: str, name: str) -> None:
        if not isinstance(workspace_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise ValueError("workspace_id is invalid")
        _choice(workspace_type, "workspace_type", WORKSPACE_TYPES)
        name = _text(name, "name")
        now = self._clock()

        def operation(cursor: Any) -> None:
            cursor.execute(self._q("workspace_insert"), (workspace_id, name))
            cursor.execute(self._q("identity_insert"), (workspace_id, workspace_type, now))

        self._run(operation, write=True)

    def add_member(self, workspace_id: str, issuer: str, subject: str, role: str | None = None) -> None:
        if not isinstance(workspace_id, str) or not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise ValueError("workspace_id is invalid")
        issuer = _identity_key(issuer, "issuer")
        subject = _identity_key(subject, "subject")
        if role is not None:
            _choice(role, "role", ROLES)
        now = self._clock()

        def operation(cursor: Any) -> None:
            cursor.execute(self._q("member_insert"), (issuer, subject, workspace_id, role, now))

        self._run(operation, write=True)

    # -- resolution --

    def memberships_for(self, principal: VerifiedPrincipal) -> tuple[WorkspaceAccess, ...]:
        def operation(cursor: Any) -> tuple[WorkspaceAccess, ...]:
            cursor.execute(self._q("memberships"), (principal.issuer, principal.subject))
            return tuple(
                WorkspaceAccess(
                    issuer=principal.issuer,
                    subject=principal.subject,
                    workspace_id=row[0],
                    workspace_type=row[1],
                    display_name=row[2],
                    role=row[3],
                )
                for row in cursor.fetchall()
            )

        return self._run(operation)

    # -- owner portfolio (workspace_type 'internal') --

    def add_portfolio_item(
        self,
        access: WorkspaceAccess,
        *,
        name: str,
        evidence_label: str,
        category: str | None = None,
        segment: str | None = None,
    ) -> PortfolioItem:
        name = _text(name, "name")
        category = _optional_text(category, "category")
        segment = _optional_text(segment, "segment")
        _choice(evidence_label, "evidence_label", EVIDENCE_LABELS)
        item_id = f"pi_{uuid.uuid4().hex}"
        now = self._clock()

        def operation(cursor: Any) -> None:
            self._require_access(cursor, access, OWNER_TYPE)
            cursor.execute(
                self._q("item_insert"),
                (item_id, access.workspace_id, name, category, segment, evidence_label, now, now),
            )

        self._run(operation, write=True)
        return PortfolioItem(item_id, access.workspace_id, name, category, segment, evidence_label)

    def list_portfolio_items(self, access: WorkspaceAccess) -> tuple[PortfolioItem, ...]:
        def operation(cursor: Any) -> tuple[PortfolioItem, ...]:
            self._require_access(cursor, access, OWNER_TYPE)
            cursor.execute(self._q("item_list"), (access.workspace_id,))
            return tuple(PortfolioItem(*row) for row in cursor.fetchall())

        return self._run(operation)

    # -- operator-managed client profile (workspace_type 'client_service') --

    def _read_profile(self, cursor: Any, workspace_id: str) -> ClientProfile | None:
        cursor.execute(self._q("profile_get"), (workspace_id,))
        row = cursor.fetchone()
        if row is None:
            return None
        cursor.execute(self._q("entry_list"), (workspace_id,))
        entries = tuple(
            ProfileEntry(entry_id, kind, label, platform or None, state)
            for entry_id, kind, label, platform, state in cursor.fetchall()
        )
        return ClientProfile(row[0], row[1], row[2], entries)

    def upsert_client_profile(self, access: WorkspaceAccess, *, company_name: str, business_type: str) -> ClientProfile:
        company_name = _text(company_name, "company_name")
        _choice(business_type, "business_type", BUSINESS_TYPES)
        now = self._clock()

        def operation(cursor: Any) -> ClientProfile:
            self._require_access(cursor, access, CLIENT_TYPE)
            cursor.execute(
                self._q("profile_upsert"), (access.workspace_id, company_name, business_type, now, now)
            )
            profile = self._read_profile(cursor, access.workspace_id)
            assert profile is not None
            return profile

        return self._run(operation, write=True)

    def add_profile_entry(
        self,
        access: WorkspaceAccess,
        *,
        kind: str,
        label: str,
        platform: str | None = None,
    ) -> ProfileEntry:
        _choice(kind, "kind", ENTRY_KINDS)
        label = _text(label, "label")
        if kind == "social_account":
            platform = _text(platform, "platform", max_len=64)
        elif platform is not None:
            raise ValueError("platform is only valid for social_account entries")
        entry_id = f"pe_{uuid.uuid4().hex}"
        now = self._clock()

        def operation(cursor: Any) -> None:
            self._require_access(cursor, access, CLIENT_TYPE)
            cursor.execute(
                self._q("entry_insert"), (entry_id, access.workspace_id, kind, label, platform or "", now)
            )

        self._run(operation, write=True)
        return ProfileEntry(entry_id, kind, label, platform, "record_only")

    def get_client_profile(self, access: WorkspaceAccess, *, permission: str | None = None) -> ClientProfile | None:
        def operation(cursor: Any) -> ClientProfile | None:
            self._require_access(cursor, access, CLIENT_TYPE, permission)
            return self._read_profile(cursor, access.workspace_id)

        return self._run(operation)

    def _insert_entries(
        self, cursor: Any, workspace_id: str, entries: Sequence[EntryInput], now: str
    ) -> None:
        for seq, (kind, label, platform) in enumerate(entries):
            # The sequence prefix keeps read order equal to input order within one write.
            entry_id = f"pe_{seq:04d}_{uuid.uuid4().hex}"
            cursor.execute(self._q("entry_insert"), (entry_id, workspace_id, kind, label, platform or "", now))

    def create_client_profile(
        self,
        access: WorkspaceAccess,
        *,
        company_name: str,
        business_type: str,
        entries: Sequence[EntryInput] = (),
        permission: str,
    ) -> ClientProfile:
        company_name = _text(company_name, "company_name")
        _choice(business_type, "business_type", BUSINESS_TYPES)
        clean_entries = _clean_entries(entries)
        now = self._clock()

        def operation(cursor: Any) -> ClientProfile:
            self._require_access(cursor, access, CLIENT_TYPE, permission)
            if self._read_profile(cursor, access.workspace_id) is not None:
                raise StorageConflict("profile_exists")
            cursor.execute(
                self._q("profile_insert"), (access.workspace_id, company_name, business_type, now, now)
            )
            self._insert_entries(cursor, access.workspace_id, clean_entries, now)
            profile = self._read_profile(cursor, access.workspace_id)
            assert profile is not None
            return profile

        return self._run(operation, write=True)

    def update_client_profile(
        self,
        access: WorkspaceAccess,
        *,
        company_name: str | None = None,
        business_type: str | None = None,
        replace_entries: Mapping[str, Sequence[EntryInput]] | None = None,
        permission: str,
    ) -> ClientProfile:
        if company_name is not None:
            company_name = _text(company_name, "company_name")
        if business_type is not None:
            _choice(business_type, "business_type", BUSINESS_TYPES)
        replacements = {kind: _clean_entries(items) for kind, items in (replace_entries or {}).items()}
        for kind in replacements:
            _choice(kind, "kind", ENTRY_KINDS)
        now = self._clock()

        def operation(cursor: Any) -> ClientProfile:
            self._require_access(cursor, access, CLIENT_TYPE, permission)
            current = self._read_profile(cursor, access.workspace_id)
            if current is None:
                raise ProfileNotFound()
            cursor.execute(
                self._q("profile_update"),
                (
                    company_name if company_name is not None else current.company_name,
                    business_type if business_type is not None else current.business_type,
                    now,
                    access.workspace_id,
                ),
            )
            for kind, items in replacements.items():
                cursor.execute(self._q("entry_delete_kind"), (access.workspace_id, kind))
                self._insert_entries(cursor, access.workspace_id, items, now)
            updated = self._read_profile(cursor, access.workspace_id)
            assert updated is not None
            return updated

        return self._run(operation, write=True)


def _quietly(call: Callable[[], Any]) -> None:
    try:
        call()
    except Exception:
        pass
