"""Fail-closed mutation boundary keyed on MARKETOS_ENVIRONMENT."""
from __future__ import annotations

import pytest

from backend.runtime.mutation_boundary import (
    ENV_VAR,
    SAFE_DENIAL_DETAIL,
    MutationBoundaryError,
    assert_local_mutation_allowed,
    mutation_boundary_decision,
    resolve_runtime_mode,
)


class TestResolveRuntimeMode:
    def test_absent(self):
        assert resolve_runtime_mode({}) is None

    def test_blank(self):
        assert resolve_runtime_mode({ENV_VAR: "  "}) is None

    def test_strips(self):
        assert resolve_runtime_mode({ENV_VAR: " local_dry_run "}) == "local_dry_run"


class TestMutationBoundaryDecision:
    def test_absent_denied(self):
        d = mutation_boundary_decision({})
        assert d["allowed"] is False
        assert d["reason"] == "runtime_mode_absent"
        assert d["mode"] is None

    def test_local_dry_run_permitted(self):
        d = mutation_boundary_decision({ENV_VAR: "local_dry_run"})
        assert d["allowed"] is True
        assert d["reason"] == "local_dry_run_permitted"

    @pytest.mark.parametrize("mode", ["staging", "production"])
    def test_hosted_denied(self, mode):
        d = mutation_boundary_decision({ENV_VAR: mode})
        assert d["allowed"] is False
        assert d["reason"] == "hosted_mode_denied"
        assert d["mode"] == mode

    def test_unrecognized_denied(self):
        d = mutation_boundary_decision({ENV_VAR: "hosted"})
        assert d["allowed"] is False
        assert d["reason"] == "unrecognized_mode_denied"


class TestAssertLocalMutationAllowed:
    def test_raises_safe_message_when_absent(self):
        with pytest.raises(MutationBoundaryError) as caught:
            assert_local_mutation_allowed({})
        assert str(caught.value) == SAFE_DENIAL_DETAIL
        assert "token" not in str(caught.value).lower()
        assert "secret" not in str(caught.value).lower()

    def test_permits_local_dry_run(self):
        d = assert_local_mutation_allowed({ENV_VAR: "local_dry_run"}, action="credentials.set")
        assert d["allowed"] is True
