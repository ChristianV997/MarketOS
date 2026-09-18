from scripts.ai.native_agent_capability import (
    PROVIDER_COMMANDS,
    build_capability_record,
    probe_agent,
)


def test_probe_agent_never_claims_more_than_installed():
    entry = probe_agent("claude")
    assert entry["installed"] in (True, False)
    for field in ("configured", "reachable", "enabled", "actually_used"):
        assert entry[field] == "not_run"
    assert entry["credential_state"] == "not_read"
    assert entry["account_id_stored"] is False


def test_probe_agent_unknown_command_is_not_run():
    entry = probe_agent("not-a-real-provider")
    assert entry["state"] == "not_run"
    assert entry["installed"] is False


def test_build_capability_record_covers_full_catalog_by_default():
    record = build_capability_record()
    names = {item["command"] for item in record["agents"]}
    assert names == set(PROVIDER_COMMANDS)
    assert record["credentials_read"] is False
    assert record["account_ids_stored"] is False
    assert record["network_calls"] is False


def test_observed_upgrade_requires_matching_evidence():
    record = build_capability_record(
        commands=["gh"],
        observed={"gh": {"enabled": "enabled", "enabled_evidence": "ran `gh auth status` and it succeeded"}},
    )
    entry = record["agents"][0]
    assert entry["enabled"] == "enabled"
    assert "rejected_claims" not in entry


def test_observed_upgrade_without_evidence_is_rejected():
    record = build_capability_record(commands=["gh"], observed={"gh": {"enabled": "enabled"}})
    entry = record["agents"][0]
    assert entry["enabled"] == "not_run"
    assert entry["rejected_claims"] == ["enabled"]


def test_installed_never_implies_configured_or_enabled():
    # `claude` is installed in this sandbox (it's this very CLI) -- confirm
    # that fact alone never upgrades any other state.
    entry = probe_agent("claude")
    if entry["installed"]:
        assert entry["state"] == "installed"
        assert entry["configured"] == "not_run"
        assert entry["enabled"] == "not_run"
        assert entry["actually_used"] == "not_run"
