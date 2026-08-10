from backend.security.rate_limit import RateLimitPolicy, check_rate_limit, explain_rate_limit_status, reset_rate_limits_for_tests


def test_rate_limit_blocks_after_policy_capacity_and_can_reset():
    reset_rate_limits_for_tests()
    policy = RateLimitPolicy("test", 2, 60)
    assert check_rate_limit(policy, "ip", now=0).allowed is True
    assert check_rate_limit(policy, "ip", now=1).allowed is True
    blocked = check_rate_limit(policy, "ip", now=2)
    assert blocked.allowed is False
    assert blocked.retry_after_seconds > 0
    reset_rate_limits_for_tests()
    assert check_rate_limit(policy, "ip", now=3).allowed is True


def test_status_is_explicitly_single_process():
    report = explain_rate_limit_status()
    assert report["enabled"] is True
    assert report["in_memory"] is True
    assert report["distributed"] is False
