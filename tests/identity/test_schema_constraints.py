"""Executes the portable 0001 migration on SQLite and attacks every constraint.

Evidence level: constraint semantics of the portable SQL subset on SQLite. The
migration has not been run against a Postgres server in this environment.
"""
from __future__ import annotations

import re
import sqlite3

import pytest

from .conftest import DOWN_SQL, PREREQUISITE_SQL, RLS_SQL, UP_SQL

TABLES = ["workspace_identity", "workspace_members", "owner_portfolio_items", "client_profiles", "client_profile_entries"]


@pytest.fixture
def db(tmp_path):
    connection = sqlite3.connect(tmp_path / "schema.db")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(PREREQUISITE_SQL)
    connection.executescript(UP_SQL.read_text(encoding="utf-8"))
    for workspace_id, name in (("w_owner", "Owner"), ("w_owner2", "Owner 2"), ("w_client", "Client")):
        connection.execute("INSERT INTO workspaces (workspace_id, name) VALUES (?, ?)", (workspace_id, name))
    connection.execute("INSERT INTO workspace_identity VALUES ('w_owner', 'internal', 't')")
    connection.execute("INSERT INTO workspace_identity VALUES ('w_owner2', 'internal', 't')")
    connection.execute("INSERT INTO workspace_identity VALUES ('w_client', 'client_service', 't')")
    connection.commit()
    yield connection
    connection.close()


def rejected(db, sql, params=()):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, params)


def item(db, workspace_id="w_owner", name="Widget", label="fixture", **extra):
    columns = {"item_id": f"pi_{workspace_id}_{name}_{label}", "workspace_id": workspace_id, "name": name,
               "evidence_label": label, "created_at": "t", "updated_at": "t", **extra}
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    return db.execute(f"INSERT INTO owner_portfolio_items ({names}) VALUES ({marks})", tuple(columns.values()))


def entry(db, kind="segment", label="SMB", platform="", state=None, entry_id=None):
    columns = {"entry_id": entry_id or f"pe_{kind}_{label}_{platform}", "workspace_id": "w_client", "kind": kind,
               "label": label, "platform": platform, "created_at": "t"}
    if state is not None:
        columns["connection_state"] = state
    names = ", ".join(columns)
    marks = ", ".join("?" for _ in columns)
    return db.execute(f"INSERT INTO client_profile_entries ({names}) VALUES ({marks})", tuple(columns.values()))


def test_migration_files_follow_the_repo_convention_and_are_idempotent(db):
    assert UP_SQL.name == "0001_identity_workspace_foundation.up.sql"
    assert DOWN_SQL.name == "0001_identity_workspace_foundation.down.sql"
    db.executescript(UP_SQL.read_text(encoding="utf-8"))  # re-apply: IF NOT EXISTS
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(TABLES) <= names


def test_up_migration_never_creates_alters_or_drops_the_existing_workspaces_table():
    for path in (UP_SQL, DOWN_SQL):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"(CREATE\s+TABLE(\s+IF\s+NOT\s+EXISTS)?|ALTER\s+TABLE|DROP\s+TABLE(\s+IF\s+EXISTS)?)\s+workspaces\b", text, re.I)


def test_no_foreign_key_cascades_deletes():
    statements = "\n".join(
        line for line in UP_SQL.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("--")
    )
    assert "CASCADE" not in statements.upper()


def test_workspace_identity_constraints(db):
    db.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('w_pub', 'Pub')")
    rejected(db, "INSERT INTO workspace_identity VALUES ('w_pub', 'public', 't')")  # CHECK type
    rejected(db, "INSERT INTO workspace_identity VALUES ('w_absent', 'internal', 't')")  # FK to workspaces
    rejected(db, "INSERT INTO workspace_identity VALUES ('w_owner', 'internal', 't')")  # PK


def test_workspace_member_constraints(db):
    db.execute("INSERT INTO workspace_members VALUES ('iss', 'sub', 'w_owner', 't')")
    rejected(db, "INSERT INTO workspace_members VALUES ('iss', 'sub', 'w_owner', 't')")  # duplicate membership
    rejected(db, "INSERT INTO workspace_members VALUES ('', 'sub', 'w_owner2', 't')")
    rejected(db, "INSERT INTO workspace_members VALUES ('iss', '', 'w_owner2', 't')")
    rejected(db, "INSERT INTO workspace_members VALUES ('iss', 'sub', 'w_absent', 't')")  # FK
    db.execute("INSERT INTO workspace_members VALUES ('other-iss', 'sub', 'w_owner', 't')")  # issuer is part of identity


def test_portfolio_only_belongs_to_owner_workspaces(db):
    item(db)
    rejected(db, "INSERT INTO owner_portfolio_items (item_id, workspace_id, name, evidence_label, created_at, updated_at) "
                 "VALUES ('pi_c', 'w_client', 'Widget', 'fixture', 't', 't')")  # composite FK: client workspace
    with pytest.raises(sqlite3.IntegrityError):
        item(db, workspace_id="w_owner2", name="Other", workspace_type="client_service")  # CHECK
    with pytest.raises(sqlite3.IntegrityError):
        item(db, workspace_id="w_absent", name="Ghost")


def test_portfolio_evidence_label_cannot_claim_live_or_measured(db):
    for label in ("live", "measured", "live_sales_validated", ""):
        with pytest.raises(sqlite3.IntegrityError):
            item(db, name=f"n-{label}", label=label)
    for label in ("fixture", "manual", "assumption", "derived", "unavailable"):
        item(db, name=f"ok-{label}", label=label)


def test_portfolio_name_rules(db):
    item(db, name="Widget")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO owner_portfolio_items (item_id, workspace_id, name, evidence_label, created_at, updated_at) "
                   "VALUES ('pi_dup', 'w_owner', 'Widget', 'fixture', 't', 't')")  # unique per workspace
    with pytest.raises(sqlite3.IntegrityError):
        item(db, name="")
    item(db, workspace_id="w_owner2", name="Widget")  # same name in another workspace is fine


def test_client_profiles_only_belong_to_client_workspaces_with_known_business_types(db):
    db.execute("INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
               "VALUES ('w_client', 'Acme', 'service_b2b', 't', 't')")
    rejected(db, "INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
                 "VALUES ('w_owner', 'Acme', 'service_b2b', 't', 't')")  # owner workspace
    rejected(db, "INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
                 "VALUES ('w_client', 'Acme again', 'service_b2b', 't', 't')")  # one profile per workspace
    db.execute("DELETE FROM client_profiles")
    rejected(db, "INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
                 "VALUES ('w_client', 'Acme', 'saas', 't', 't')")
    rejected(db, "INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
                 "VALUES ('w_client', '', 'product', 't', 't')")
    for business_type in ("service_b2c", "service_b2b", "product", "other"):
        db.execute("DELETE FROM client_profiles")
        db.execute("INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
                   "VALUES ('w_client', 'Acme', ?, 't', 't')", (business_type,))


def test_profile_entries_are_record_only_and_platform_rules_hold(db):
    db.execute("INSERT INTO client_profiles (workspace_id, company_name, business_type, created_at, updated_at) "
               "VALUES ('w_client', 'Acme', 'product', 't', 't')")
    for kind in ("segment", "target_market", "offering"):
        entry(db, kind=kind, label="x")
    entry(db, kind="social_account", label="acme", platform="instagram")
    entry(db, kind="social_account", label="acme", platform="tiktok")  # same handle, different platform
    with pytest.raises(sqlite3.IntegrityError):
        entry(db, kind="social_account", label="acme", platform="instagram", entry_id="pe_dup")  # duplicate
    with pytest.raises(sqlite3.IntegrityError):
        entry(db, kind="social_account", label="acme", platform="")  # social requires a platform
    with pytest.raises(sqlite3.IntegrityError):
        entry(db, kind="segment", label="SMB", platform="instagram")  # platform only for social
    with pytest.raises(sqlite3.IntegrityError):
        entry(db, kind="newsletter", label="x")
    with pytest.raises(sqlite3.IntegrityError):
        entry(db, kind="social_account", label="acme2", platform="x", state="connected")  # never 'connected'
    with pytest.raises(sqlite3.IntegrityError):
        entry(db, kind="offering", label="")
    assert {row[0] for row in db.execute("SELECT connection_state FROM client_profile_entries")} == {"record_only"}


def test_entries_require_an_existing_profile(db):
    with pytest.raises(sqlite3.IntegrityError):
        entry(db)


def test_dependents_block_workspace_deletion_instead_of_cascading(db):
    item(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM workspace_identity WHERE workspace_id = 'w_owner'")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM workspaces WHERE workspace_id = 'w_owner'")
    assert db.execute("SELECT COUNT(*) FROM owner_portfolio_items").fetchone()[0] == 1


def test_down_migration_removes_only_the_foundation_tables_and_is_reversible(db):
    db.executescript(DOWN_SQL.read_text(encoding="utf-8"))
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert not set(TABLES) & names
    assert "workspaces" in names
    assert db.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 3
    db.executescript(DOWN_SQL.read_text(encoding="utf-8"))  # idempotent
    db.executescript(UP_SQL.read_text(encoding="utf-8"))
    assert set(TABLES) <= {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_every_table_has_row_level_security_enabled_without_policies():
    created = re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", UP_SQL.read_text(encoding="utf-8"))
    rls_text = RLS_SQL.read_text(encoding="utf-8")
    enabled = re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", rls_text)
    assert sorted(created) == sorted(TABLES) == sorted(enabled)
    assert "CREATE POLICY" not in rls_text.upper()
