"""Principal-to-workspace resolution: selectors choose among memberships, never grant."""
from __future__ import annotations

import pytest

from backend.identity.errors import WorkspaceAccessDenied, WorkspaceSelectionRequired
from backend.identity.workspaces import resolve_workspace

from .conftest import ALICE, BOB, access_for


class FakeRepository:
    def __init__(self, rows):
        self.rows = list(rows)
        self.asked = []

    def memberships_for(self, principal):
        self.asked.append(principal)
        return tuple(self.rows)


def test_single_membership_is_used_when_no_selector_is_given():
    repo = FakeRepository([access_for(ALICE, "ws_a")])
    assert resolve_workspace(ALICE, None, repo).workspace_id == "ws_a"
    assert resolve_workspace(ALICE, "   ", repo).workspace_id == "ws_a"
    assert repo.asked == [ALICE, ALICE]


def test_selector_picks_among_the_principals_own_memberships():
    repo = FakeRepository([access_for(ALICE, "ws_b"), access_for(ALICE, "ws_a")])
    assert resolve_workspace(ALICE, "ws_b", repo).workspace_id == "ws_b"
    assert resolve_workspace(ALICE, " ws_a ", repo).workspace_id == "ws_a"


def test_several_memberships_without_a_selector_require_one():
    repo = FakeRepository([access_for(ALICE, "ws_b"), access_for(ALICE, "ws_a")])
    with pytest.raises(WorkspaceSelectionRequired) as caught:
        resolve_workspace(ALICE, None, repo)
    assert caught.value.status_code == 400


def test_no_membership_is_403():
    with pytest.raises(WorkspaceAccessDenied) as caught:
        resolve_workspace(ALICE, None, FakeRepository([]))
    assert (caught.value.status_code, caught.value.code) == (403, "no_workspace_membership")


def test_forged_selector_never_falls_back_to_the_only_membership():
    repo = FakeRepository([access_for(ALICE, "ws_a")])
    with pytest.raises(WorkspaceAccessDenied) as caught:
        resolve_workspace(ALICE, "ws_of_someone_else", repo)
    assert (caught.value.status_code, caught.value.code) == (403, "workspace_not_authorized")


def test_workspace_names_never_select_a_workspace():
    row = access_for(ALICE, "ws_a", name="acme")
    with pytest.raises(WorkspaceAccessDenied):
        resolve_workspace(ALICE, "acme", FakeRepository([row]))
    with pytest.raises(WorkspaceAccessDenied):
        resolve_workspace(ALICE, "Acme Corp", FakeRepository([access_for(ALICE, "ws_a", name="Acme Corp")]))


@pytest.mark.parametrize("selector", ["../ws_a", "ws_a; DROP TABLE workspaces", "ws a", "ws_a\nX: y", "w" * 129, "ws_a/../ws_b"])
def test_malformed_selectors_are_denied(selector):
    with pytest.raises(WorkspaceAccessDenied):
        resolve_workspace(ALICE, selector, FakeRepository([access_for(ALICE, "ws_a")]))


def test_denial_does_not_reveal_whether_the_workspace_exists():
    repo = FakeRepository([access_for(ALICE, "ws_a")])
    codes = []
    for selector in ("ws_missing", "ws_bobs_real_workspace"):
        with pytest.raises(WorkspaceAccessDenied) as caught:
            resolve_workspace(ALICE, selector, repo)
        codes.append((caught.value.status_code, caught.value.code))
    assert codes[0] == codes[1]


def test_rows_belonging_to_other_principals_are_ignored():
    repo = FakeRepository([access_for(BOB, "ws_bob")])
    with pytest.raises(WorkspaceAccessDenied):
        resolve_workspace(ALICE, "ws_bob", repo)
    with pytest.raises(WorkspaceAccessDenied):
        resolve_workspace(ALICE, None, repo)
