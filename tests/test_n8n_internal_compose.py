from scripts.validate_n8n_internal_compose import validate_overlay


def test_internal_n8n_compose_overlay_is_pinned_private_and_health_gated():
    assert validate_overlay() == []
