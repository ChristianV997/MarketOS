"""Role policy, role-aware repository methods and the reversible 0002 migration."""
from __future__ import annotations

import re
import sqlite3

import pytest

from backend.identity.errors import ProfileNotFound, StorageConflict, WorkspaceAccessDenied
from backend.identity.roles import (
    CLIENT_VIEWER,
    INTERNAL_OPERATOR,
    PROFILE_CREATE,
    PROFILE_READ,
    PROFILE_UPDATE,
    ROLE_PERMISSIONS,
    role_grants,
)
from backend.identity.workspaces import WorkspaceAccess

from .conftest import (
    ALICE,
    BOB,
    CLIENT_ACME,
    DOWN2_SQL,
    MIGRATIONS,
    OWNER_ALICE,
    PREREQUISITE_SQL,
    RLS_SQL,
    UP2_SQL,
    UP_SQL,
)


def _access(principal, workspace_id, workspace_type, role):
    return WorkspaceAccess(principal.issuer, principal.subject, workspace_id, workspace_type, "n", role)


@pytest.fixture
def roles_repo(repo):
    repo.create_workspace(OWNER_ALICE, "internal", "Alice")
    repo.create_workspace(CLIENT_ACME, "client_service", "Acme")
    repo.add_member(CLIENT_ACME, ALICE.issuer, ALICE.subject, CLIENT_VIEWER)
    repo.add_member(CLIENT_ACME, BOB.issuer, BOB.subject, INTERNAL_OPERATOR)
    return repo


# ------------------------------------------------------------------ policy


def test_policy_is_closed_by_default():
    assert role_grants(INTERNAL_OPERATOR, PROFILE_UPDATE)
    assert role_grants(CLIENT_VIEWER, PROFILE_READ)
    assert not role_grants(CLIENT_VIEWER, PROFILE_CREATE)
    assert not role_grants(CLIENT_VIEWER, PROFILE_UPDATE)
    for role in (None, "", "admin", "Internal_Operator", 3, ["internal_operator"]):
        assert not role_grants(role, PROFILE_READ)
    assert not role_grants(INTERNAL_OPERATOR, "client_profile:delete")
    assert set(ROLE_PERMISSIONS) == {CLIENT_VIEWER, INTERNAL_OPERATOR}


def test_add_member_rejects_unknown_roles(roles_repo):
    with pytest.raises(ValueError):
        roles_repo.add_member(CLIENT_ACME, "https://i", "sub", "admin")


def test_memberships_carry_the_stored_role(roles_repo):
    (access,) = roles_repo.memberships_for(ALICE)
    assert (access.workspace_id, access.role) == (CLIENT_ACME, CLIENT_VIEWER)


# ------------------------------------------------------------------ repository enforces the stored role


def test_forged_role_on_the_access_object_is_not_trusted(roles_repo):
    forged = _access(ALICE, CLIENT_ACME, "client_service", INTERNAL_OPERATOR)  # stored role: client_viewer
    with pytest.raises(WorkspaceAccessDenied) as caught:
        roles_repo.create_client_profile(forged, company_name="X", business_type="other", permission=PROFILE_CREATE)
    assert caught.value.code == "role_not_authorized"
    with pytest.raises(WorkspaceAccessDenied):
        roles_repo.update_client_profile(forged, company_name="X", permission=PROFILE_UPDATE)


def test_null_stored_role_reads_nothing(roles_repo):
    roles_repo.add_member(OWNER_ALICE, BOB.issuer, BOB.subject)  # no role
    access = _access(BOB, OWNER_ALICE, "internal", INTERNAL_OPERATOR)
    with pytest.raises(WorkspaceAccessDenied):
        roles_repo.get_client_profile(access, permission=PROFILE_READ)


def test_non_member_and_wrong_workspace_type_are_denied(roles_repo):
    outsider = _access(BOB, OWNER_ALICE, "internal", INTERNAL_OPERATOR)  # BOB is not a member of OWNER_ALICE
    with pytest.raises(WorkspaceAccessDenied):
        roles_repo.create_client_profile(outsider, company_name="X", business_type="other", permission=PROFILE_CREATE)
    roles_repo.add_member(OWNER_ALICE, BOB.issuer, BOB.subject, INTERNAL_OPERATOR)
    with pytest.raises(WorkspaceAccessDenied) as caught:  # a member, but of an owner workspace
        roles_repo.create_client_profile(outsider, company_name="X", business_type="other", permission=PROFILE_CREATE)
    assert caught.value.code == "workspace_type_mismatch"


def test_create_conflict_and_update_not_found_are_distinct_errors(roles_repo):
    operator = _access(BOB, CLIENT_ACME, "client_service", INTERNAL_OPERATOR)
    with pytest.raises(ProfileNotFound):
        roles_repo.update_client_profile(operator, company_name="X", permission=PROFILE_UPDATE)
    roles_repo.create_client_profile(operator, company_name="Acme", business_type="other", permission=PROFILE_CREATE)
    with pytest.raises(StorageConflict) as caught:
        roles_repo.create_client_profile(operator, company_name="Acme 2", business_type="other", permission=PROFILE_CREATE)
    assert caught.value.code == "profile_exists"
    assert roles_repo.get_client_profile(operator).company_name == "Acme"


def test_failed_update_rolls_back_every_part(roles_repo):
    operator = _access(BOB, CLIENT_ACME, "client_service", INTERNAL_OPERATOR)
    roles_repo.create_client_profile(
        operator, company_name="Acme", business_type="other",
        entries=[("segment", "keep me", None)], permission=PROFILE_CREATE,
    )
    with pytest.raises(ValueError):
        roles_repo.update_client_profile(
            operator,
            company_name="Renamed",
            replace_entries={"segment": [("segment", "a", None), ("segment", "a", None)]},
            permission=PROFILE_UPDATE,
        )
    profile = roles_repo.get_client_profile(operator)
    assert profile.company_name == "Acme" and [e.label for e in profile.entries] == ["keep me"]


def test_entry_platform_rules_hold_for_new_methods(roles_repo):
    operator = _access(BOB, CLIENT_ACME, "client_service", INTERNAL_OPERATOR)
    for entries in ([("social_account", "a", None)], [("segment", "a", "instagram")], [("bogus", "a", None)]):
        with pytest.raises(ValueError):
            roles_repo.create_client_profile(
                operator, company_name="A", business_type="other", entries=entries, permission=PROFILE_CREATE
            )


# ------------------------------------------------------------------ migration 0002


@pytest.fixture
def migrated(tmp_path):
    path = tmp_path / "m.db"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(PREREQUISITE_SQL)
    connection.executescript(UP_SQL.read_text(encoding="utf-8"))
    connection.execute("INSERT INTO workspaces (workspace_id, name) VALUES ('w', 'W')")
    connection.execute("INSERT INTO workspace_identity VALUES ('w', 'client_service', 't')")
    connection.execute("INSERT INTO workspace_members VALUES ('i', 'legacy', 'w', 't')")
    connection.commit()
    yield connection
    connection.close()


def _columns(connection):
    return [row[1] for row in connection.execute("PRAGMA table_info(workspace_members)")]


def test_up_keeps_existing_memberships_with_no_role(migrated):
    migrated.executescript(UP2_SQL.read_text(encoding="utf-8"))
    assert _columns(migrated)[-1] == "role"
    assert migrated.execute("SELECT subject, role FROM workspace_members").fetchall() == [("legacy", None)]


def test_role_check_rejects_unknown_values_but_allows_known_and_null(migrated):
    migrated.executescript(UP2_SQL.read_text(encoding="utf-8"))
    for index, role in enumerate((None, "client_viewer", "internal_operator")):
        migrated.execute("INSERT INTO workspace_members VALUES (?, 's', 'w', 't', ?)", (f"i{index}", role))
    for bad in ("admin", "", "Client_Viewer"):
        with pytest.raises(sqlite3.IntegrityError):
            migrated.execute("INSERT INTO workspace_members VALUES ('ix', 's2', 'w', 't', ?)", (bad,))


def test_down_removes_only_the_role_column_and_is_reversible(migrated):
    migrated.executescript(UP2_SQL.read_text(encoding="utf-8"))
    migrated.execute("INSERT INTO workspace_members VALUES ('i2', 'op', 'w', 't', 'internal_operator')")
    migrated.executescript(DOWN2_SQL.read_text(encoding="utf-8"))
    assert "role" not in _columns(migrated)
    assert migrated.execute("SELECT COUNT(*) FROM workspace_members").fetchone()[0] == 2
    migrated.executescript(UP2_SQL.read_text(encoding="utf-8"))
    assert _columns(migrated)[-1] == "role"


def test_0002_adds_no_table_so_the_existing_rls_file_still_covers_every_table():
    sql = "\n".join(
        line for line in UP2_SQL.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("--")
    ).upper()
    assert "CREATE TABLE" not in sql and "DROP" not in sql
    assert "workspace_members" in re.findall(r"ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", RLS_SQL.read_text(encoding="utf-8"))
    assert sorted(p.name for p in MIGRATIONS.glob("0002_*")) == [
        "0002_workspace_member_roles.down.sql",
        "0002_workspace_member_roles.up.sql",
    ]
