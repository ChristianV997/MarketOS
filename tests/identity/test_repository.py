"""PostgresWorkspaceRepository over SQLite (qmark) plus a recording fake (format/%s)."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import replace

import pytest

from backend.identity.errors import StorageConflict, StorageUnavailable, WorkspaceAccessDenied
from backend.identity.repository import _SQL, PostgresWorkspaceRepository
from backend.identity.workspaces import resolve_workspace

from .conftest import ALICE, BOB, CAROL, CLIENT_ACME, DAVE, ISSUER, OWNER_ALICE, OWNER_BOB, OWNER_DAVE, access_for, sqlite_connect


def owner_access(repo, principal, workspace_id):
    return resolve_workspace(principal, workspace_id, repo)


# ----- membership / provisioning -----

def test_memberships_are_per_principal_and_ordered(seeded):
    assert [m.workspace_id for m in seeded.memberships_for(DAVE)] == [CLIENT_ACME, OWNER_DAVE]
    assert {m.workspace_type for m in seeded.memberships_for(DAVE)} == {"internal", "client_service"}
    assert [m.display_name for m in seeded.memberships_for(ALICE)] == ["Alice Owner Workspace"]
    assert seeded.memberships_for(CAROL) == ()


def test_membership_is_keyed_by_issuer_and_subject(seeded):
    other_issuer = replace(ALICE, issuer="https://other-issuer.test")
    assert seeded.memberships_for(other_issuer) == ()


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.create_workspace("bad id", "internal", "x"),
        lambda r: r.create_workspace("ws_ok", "public", "x"),
        lambda r: r.create_workspace("ws_ok", "internal", "  "),
        lambda r: r.create_workspace("ws_ok", "live", "x"),
        lambda r: r.add_member("bad id", ISSUER, "u"),
        lambda r: r.add_member("ws_owner_alice", "", "u"),
        lambda r: r.add_member("ws_owner_alice", ISSUER, "u\x00"),
        lambda r: r.add_member("ws_owner_alice", ISSUER, " user_x"),
        lambda r: r.add_member("ws_owner_alice", ISSUER + " ", "user_x"),
    ],
)
def test_provisioning_rejects_invalid_input_before_touching_storage(seeded, call):
    with pytest.raises(ValueError):
        call(seeded)


def test_duplicate_workspace_and_orphan_membership_are_conflicts(seeded):
    with pytest.raises(StorageConflict):
        seeded.create_workspace(OWNER_ALICE, "internal", "Again")
    with pytest.raises(StorageConflict):
        seeded.add_member("ws_missing", ISSUER, "user_x")
    with pytest.raises(StorageConflict):
        seeded.add_member(OWNER_ALICE, ALICE.issuer, ALICE.subject)


# ----- owner portfolio -----

def test_portfolio_is_scoped_to_the_workspace_and_labelled_truthfully(seeded):
    alice, bob = owner_access(seeded, ALICE, OWNER_ALICE), owner_access(seeded, BOB, OWNER_BOB)
    created = seeded.add_portfolio_item(alice, name="Smart feeder", evidence_label="fixture", category="pets", segment="owners")
    seeded.add_portfolio_item(alice, name="Espresso maker", evidence_label="assumption")
    seeded.add_portfolio_item(bob, name="Smart feeder", evidence_label="manual")  # same name, other workspace

    listed = seeded.list_portfolio_items(alice)
    assert [i.name for i in listed] == ["Smart feeder", "Espresso maker"]
    assert listed[0] == created
    assert {i.workspace_id for i in listed} == {OWNER_ALICE}
    assert [i.evidence_label for i in seeded.list_portfolio_items(bob)] == ["manual"]


def test_portfolio_rejects_duplicate_names_and_unsupported_labels(seeded):
    alice = owner_access(seeded, ALICE, OWNER_ALICE)
    seeded.add_portfolio_item(alice, name="Widget", evidence_label="derived")
    with pytest.raises(StorageConflict):
        seeded.add_portfolio_item(alice, name="Widget", evidence_label="derived")
    for label in ("measured", "live", "", None):
        with pytest.raises(ValueError):
            seeded.add_portfolio_item(alice, name="Other", evidence_label=label)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        seeded.add_portfolio_item(alice, name=" ", evidence_label="fixture")


# ----- cross-workspace denial (defense in depth, even with a forged access object) -----

def test_forged_access_to_another_principals_workspace_is_denied_and_writes_nothing(seeded, db_path):
    forged = access_for(ALICE, OWNER_BOB)  # alice is not a member of bob's workspace
    with pytest.raises(WorkspaceAccessDenied) as caught:
        seeded.list_portfolio_items(forged)
    assert caught.value.code == "workspace_not_authorized"
    with pytest.raises(WorkspaceAccessDenied):
        seeded.add_portfolio_item(forged, name="Planted", evidence_label="fixture")
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM owner_portfolio_items").fetchone()[0] == 0


def test_workspace_type_is_taken_from_the_database_not_from_the_access_object(seeded):
    honest_owner = owner_access(seeded, ALICE, OWNER_ALICE)
    lying = replace(honest_owner, workspace_type="client_service")
    with pytest.raises(WorkspaceAccessDenied) as caught:
        seeded.upsert_client_profile(lying, company_name="Acme", business_type="product")
    assert caught.value.code == "workspace_type_mismatch"
    client = owner_access(seeded, DAVE, CLIENT_ACME)
    with pytest.raises(WorkspaceAccessDenied) as caught:
        seeded.list_portfolio_items(replace(client, workspace_type="internal"))
    assert caught.value.code == "workspace_type_mismatch"


# ----- operator-managed client profiles -----

def test_client_profile_lifecycle_with_record_only_social_accounts(seeded):
    client = owner_access(seeded, DAVE, CLIENT_ACME)
    assert seeded.get_client_profile(client) is None
    profile = seeded.upsert_client_profile(client, company_name="Acme Corp", business_type="service_b2b")
    assert (profile.company_name, profile.business_type, profile.entries) == ("Acme Corp", "service_b2b", ())

    seeded.add_profile_entry(client, kind="segment", label="Mid-market")
    seeded.add_profile_entry(client, kind="target_market", label="DE")
    seeded.add_profile_entry(client, kind="offering", label="Retainer")
    social = seeded.add_profile_entry(client, kind="social_account", label="acme_co", platform="instagram")
    seeded.add_profile_entry(client, kind="social_account", label="acme_co", platform="tiktok")
    assert social.connection_state == "record_only"

    updated = seeded.upsert_client_profile(client, company_name="Acme Corporation", business_type="product")
    assert (updated.company_name, updated.business_type) == ("Acme Corporation", "product")
    fetched = seeded.get_client_profile(client)
    assert [(e.kind, e.label, e.platform) for e in fetched.entries] == [
        ("segment", "Mid-market", None),
        ("target_market", "DE", None),
        ("offering", "Retainer", None),
        ("social_account", "acme_co", "instagram"),
        ("social_account", "acme_co", "tiktok"),
    ]
    assert {e.connection_state for e in fetched.entries} == {"record_only"}


def test_client_profile_input_rules_and_conflicts(seeded):
    client = owner_access(seeded, DAVE, CLIENT_ACME)
    for business_type in ("saas", "", None):
        with pytest.raises(ValueError):
            seeded.upsert_client_profile(client, company_name="Acme", business_type=business_type)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        seeded.upsert_client_profile(client, company_name="", business_type="product")
    with pytest.raises(StorageConflict):  # entries need an existing profile
        seeded.add_profile_entry(client, kind="segment", label="SMB")
    seeded.upsert_client_profile(client, company_name="Acme", business_type="product")
    with pytest.raises(ValueError):
        seeded.add_profile_entry(client, kind="social_account", label="acme")  # platform required
    with pytest.raises(ValueError):
        seeded.add_profile_entry(client, kind="segment", label="SMB", platform="instagram")
    with pytest.raises(ValueError):
        seeded.add_profile_entry(client, kind="newsletter", label="x")
    seeded.add_profile_entry(client, kind="segment", label="SMB")
    with pytest.raises(StorageConflict):
        seeded.add_profile_entry(client, kind="segment", label="SMB")


def test_owner_workspace_cannot_hold_a_client_profile_and_vice_versa(seeded):
    owner = owner_access(seeded, ALICE, OWNER_ALICE)
    with pytest.raises(WorkspaceAccessDenied):
        seeded.get_client_profile(owner)
    with pytest.raises(WorkspaceAccessDenied):
        seeded.add_profile_entry(owner, kind="segment", label="x")


# ----- unavailable database: fail closed, no fallback, no leakage -----

def test_connect_failure_is_storage_unavailable_without_leaking_connection_details(caplog):
    def connect():
        raise RuntimeError("connect refused canary-secret-xyz at db.internal")

    repo = PostgresWorkspaceRepository(connect)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(StorageUnavailable) as caught:
            repo.memberships_for(ALICE)
    assert (caught.value.status_code, caught.value.code) == (503, "storage_unavailable")
    assert str(caught.value) == "storage_unavailable"
    assert caught.value.__cause__ is None
    assert "canary-secret-xyz" not in caplog.text and "db.internal" not in caplog.text
    assert "RuntimeError" in caplog.text


def test_unmigrated_database_is_storage_unavailable(tmp_path):
    empty = tmp_path / "empty.db"
    repo = PostgresWorkspaceRepository(sqlite_connect(empty), paramstyle="qmark")
    with pytest.raises(StorageUnavailable):
        repo.memberships_for(ALICE)


def test_there_is_no_default_connection_or_fallback_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(TypeError):
        PostgresWorkspaceRepository(None)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        PostgresWorkspaceRepository()  # type: ignore[call-arg]

    def unreachable():
        raise OSError("down")

    repo = PostgresWorkspaceRepository(unreachable)
    for call in (
        lambda: repo.memberships_for(ALICE),
        lambda: repo.create_workspace("ws_x", "internal", "X"),
        lambda: repo.add_member("ws_x", ISSUER, "u"),
    ):
        with pytest.raises(StorageUnavailable):
            call()
    assert list(tmp_path.iterdir()) == []


class _FailingCursor:
    def __init__(self, cursor, state):
        self._cursor, self._state = cursor, state

    def execute(self, sql, params=()):
        self._state["executed"] += 1
        if self._state["executed"] == self._state["fail_at"]:
            raise sqlite3.OperationalError("disk I/O error")
        return self._cursor.execute(sql, params)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _FailingConnection:
    def __init__(self, connection, state):
        self._connection, self._state = connection, state

    def cursor(self):
        return _FailingCursor(self._connection.cursor(), self._state)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def test_multi_statement_writes_are_atomic(repo, db_path):
    state = {"executed": 0, "fail_at": 2}
    flaky = PostgresWorkspaceRepository(
        lambda: _FailingConnection(sqlite_connect(db_path)(), state), paramstyle="qmark", clock=lambda: "t"
    )
    with pytest.raises(StorageUnavailable):
        flaky.create_workspace("ws_half", "internal", "Half written")
    connection = sqlite3.connect(db_path)
    assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM workspace_identity").fetchone()[0] == 0


# ----- Postgres-style SQL path (format paramstyle), no server required -----

class _RecordingCursor:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql, params=()):
        self._connection.executed.append((sql, tuple(params)))
        if self._connection.raise_on is not None:
            raise self._connection.raise_on

    def fetchall(self):
        return self._connection.rows

    def fetchone(self):
        return self._connection.rows[0] if self._connection.rows else None

    def close(self):
        pass


class _RecordingConnection:
    def __init__(self, rows=(), raise_on=None):
        self.rows, self.raise_on = list(rows), raise_on
        self.executed, self.commits, self.rollbacks, self.closed = [], 0, 0, False

    def cursor(self):
        return _RecordingCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_format_paramstyle_emits_percent_s_placeholders():
    connection = _RecordingConnection(rows=[("ws_a", "internal", "Alice WS")])
    repo = PostgresWorkspaceRepository(lambda: connection)
    (access,) = repo.memberships_for(ALICE)
    (sql, params), = connection.executed
    assert "%s" in sql and "?" not in sql
    assert params == (ALICE.issuer, ALICE.subject)
    assert (access.workspace_id, access.workspace_type, access.display_name) == ("ws_a", "internal", "Alice WS")
    assert connection.commits == 0 and connection.closed is True


def test_format_paramstyle_write_commits_once_and_closes():
    connection = _RecordingConnection()
    repo = PostgresWorkspaceRepository(lambda: connection, clock=lambda: "t")
    repo.create_workspace("ws_new", "client_service", "Acme")
    assert [params for _, params in connection.executed] == [("ws_new", "Acme"), ("ws_new", "client_service", "t")]
    assert all("?" not in sql for sql, _ in connection.executed)
    assert (connection.commits, connection.rollbacks, connection.closed) == (1, 0, True)


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (type("IntegrityError", (Exception,), {})("dup"), StorageConflict),
        (type("UniqueViolation", (type("IntegrityError", (Exception,), {}),), {})("dup"), StorageConflict),
        (type("OperationalError", (Exception,), {})("down"), StorageUnavailable),
        (type("UndefinedTable", (type("ProgrammingError", (Exception,), {}),), {})("no table"), StorageUnavailable),
    ],
)
def test_driver_errors_map_by_dbapi_class_name_and_roll_back(raised, expected):
    connection = _RecordingConnection(raise_on=raised)
    repo = PostgresWorkspaceRepository(lambda: connection, clock=lambda: "t")
    with pytest.raises(expected) as caught:
        repo.add_member("ws_a", ISSUER, "user_x")
    assert caught.value.__cause__ is None
    assert (connection.commits, connection.rollbacks, connection.closed) == (0, 1, True)


def test_unexpected_errors_are_not_masked_but_still_roll_back_and_close():
    connection = _RecordingConnection(raise_on=KeyError("bug"))
    repo = PostgresWorkspaceRepository(lambda: connection, clock=lambda: "t")
    with pytest.raises(KeyError):
        repo.add_member("ws_a", ISSUER, "user_x")
    assert (connection.commits, connection.rollbacks, connection.closed) == (0, 1, True)


def test_every_statement_translates_cleanly_for_psycopg():
    for key, sql in _SQL.items():
        assert "%" not in sql, key
        translated = PostgresWorkspaceRepository(lambda: None)._q(key)  # type: ignore[arg-type,return-value]
        assert "?" not in translated and translated.count("%s") == sql.count("?"), key
