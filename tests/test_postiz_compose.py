from scripts.validate_postiz_compose import validate_overlay


def test_postiz_compose_overlay_is_digest_pinned_private_and_approval_gated():
    assert validate_overlay() == []
