from __future__ import annotations

import pytest

from backend.runtime.mvp_mode import (
    MVPModeError,
    assert_action_allowed,
    disabled_modules,
    enabled_modules,
    is_mvp_mode_enabled,
    mvp_readiness_report,
)


def test_mode_is_default_off_and_uses_explicit_environment() -> None:
    assert not is_mvp_mode_enabled({})
    assert is_mvp_mode_enabled({"MARKETOS_MVP_MODE": "true"})


def test_profile_allows_island_capabilities_and_blocks_live_actions() -> None:
    assert "advisory_reports" in enabled_modules()
    assert "live_ads" in disabled_modules()
    assert_action_allowed("public_signal_ingestion")
    assert_action_allowed("manual_approval")
    with pytest.raises(MVPModeError, match="blocks"):
        assert_action_allowed("launch")


def test_readiness_classifies_environment_without_enabling_anything() -> None:
    report = mvp_readiness_report({"MARKETOS_MVP_MODE": "1", "ALLOWED_ORIGINS": "https://example.test"})
    assert report["status"] == "ready"
    assert report["unsafe_live_flags"] == []
    assert report["supabase_configured"] is False
    assert report["public_network_enabled"] is False


def test_readiness_fails_closed_for_live_flag_or_disabled_dry_run() -> None:
    report = mvp_readiness_report({
        "MARKETOS_MVP_MODE": "1", "ALLOWED_ORIGINS": "https://example.test",
        "CAPITAL_POLICY_LIVE": "true", "META_DRY_RUN": "false",
    })
    assert report["status"] == "blocked"
    assert set(report["unsafe_live_flags"]) == {"CAPITAL_POLICY_LIVE", "META_DRY_RUN"}
