from scripts.validate_oss_compose import validate_overlay


def test_oss_compose_overlay_is_health_gated_and_pinned():
    assert validate_overlay() == []
