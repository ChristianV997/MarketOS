from backend.signals.public_signal_policy import public_rss_policy, public_source_capabilities, validate_public_ingestion_request


def test_public_rss_policy_is_no_credential_read_only_and_bounded():
    policy = public_rss_policy()
    assert policy.requires_credentials is False
    assert policy.requires_explicit_network_opt_in is True
    assert policy.maximum_records == 25
    assert "read_public_only" in policy.allowed_actions
    assert {"publish", "spend", "mutate", "login", "browser_automation"}.issubset(policy.forbidden_actions)


def test_ingestion_guard_requires_fixture_or_explicit_network_and_clamps_nothing_silently():
    fixture = validate_public_ingestion_request("rss", "  ecommerce   trends ", 5, allow_network=False, fixture_mode=True)
    assert fixture.allowed is True
    assert fixture.normalized_query == "ecommerce trends"
    blocked = validate_public_ingestion_request("rss", "topic", 5, allow_network=False, fixture_mode=False)
    assert blocked.allowed is False
    assert blocked.reasons == ["network_opt_in_required"]
    excessive = validate_public_ingestion_request("rss", "topic", 26, allow_network=True, fixture_mode=False)
    assert excessive.allowed is False
    assert "limit_exceeds_maximum:25" in excessive.reasons
    unsupported = validate_public_ingestion_request("reddit", "topic", 5, allow_network=True, fixture_mode=False)
    assert unsupported.allowed is False
    assert "unsupported_public_source" in unsupported.reasons
    assert public_source_capabilities()[0]["requires_credentials"] is False
