"""Shared fixtures: SQLite stands in for Postgres to exercise the portable SQL.

The prerequisite ``workspaces`` table mirrors deploy/supabase/schema.sql's
columns in a SQLite-compatible form. Nothing here touches a real database,
network, credentials, or repository state; databases live under ``tmp_path``.
"""
from __future__ import annotations

import sqlite3
from itertools import count
from pathlib import Path

import pytest

from backend.identity.principal import VerifiedPrincipal
from backend.identity.repository import PostgresWorkspaceRepository, new_workspace_id  # noqa: F401
from backend.identity.workspaces import WorkspaceAccess

MIGRATIONS = Path(__file__).resolve().parents[2] / "backend" / "identity" / "migrations"
UP_SQL = MIGRATIONS / "0001_identity_workspace_foundation.up.sql"
DOWN_SQL = MIGRATIONS / "0001_identity_workspace_foundation.down.sql"
RLS_SQL = MIGRATIONS / "0001_identity_workspace_foundation.rls.sql"

PREREQUISITE_SQL = """
CREATE TABLE workspaces (
    workspace_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT 'MarketOS workspace',
    created_at TEXT NOT NULL DEFAULT '',
    metadata TEXT NOT NULL DEFAULT '{}'
);
"""

ISSUER = "https://clerk.test"
ALICE = VerifiedPrincipal(ISSUER, "user_alice")
BOB = VerifiedPrincipal(ISSUER, "user_bob")
CAROL = VerifiedPrincipal(ISSUER, "user_carol")  # authenticated, member of nothing
DAVE = VerifiedPrincipal(ISSUER, "user_dave")  # member of an owner and a client workspace

OWNER_ALICE = "ws_owner_alice"
OWNER_BOB = "ws_owner_bob"
OWNER_DAVE = "ws_owner_dave"
CLIENT_ACME = "ws_client_acme"


def sqlite_connect(path: Path):
    def connect() -> sqlite3.Connection:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    return connect


def access_for(principal: VerifiedPrincipal, workspace_id: str, workspace_type: str = "internal", name: str = "n") -> WorkspaceAccess:
    return WorkspaceAccess(principal.issuer, principal.subject, workspace_id, workspace_type, name)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "identity.db"
    connection = sqlite3.connect(path)
    connection.executescript(PREREQUISITE_SQL)
    connection.executescript(UP_SQL.read_text(encoding="utf-8"))
    connection.commit()
    connection.close()
    return path


@pytest.fixture
def repo(db_path: Path) -> PostgresWorkspaceRepository:
    ticks = count()
    return PostgresWorkspaceRepository(
        sqlite_connect(db_path), paramstyle="qmark", clock=lambda: f"t{next(ticks):06d}"
    )


@pytest.fixture
def seeded(repo: PostgresWorkspaceRepository) -> PostgresWorkspaceRepository:
    repo.create_workspace(OWNER_ALICE, "internal", "Alice Owner Workspace")
    repo.create_workspace(OWNER_BOB, "internal", "Bob Owner Workspace")
    repo.create_workspace(OWNER_DAVE, "internal", "Dave Owner Workspace")
    repo.create_workspace(CLIENT_ACME, "client_service", "Acme Corp")
    repo.add_member(OWNER_ALICE, ALICE.issuer, ALICE.subject)
    repo.add_member(OWNER_BOB, BOB.issuer, BOB.subject)
    repo.add_member(OWNER_DAVE, DAVE.issuer, DAVE.subject)
    repo.add_member(CLIENT_ACME, DAVE.issuer, DAVE.subject)
    return repo
