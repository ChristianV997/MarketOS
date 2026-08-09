from backend.execution_cockpit.action_catalog import get_cockpit_action_catalog


def test_catalog_is_explicit_and_non_external():
    catalog = get_cockpit_action_catalog()
    for name in ("run_workflow", "generate_optimization", "create_operating_plan", "run_refinement", "advisory_manual", "blocked"):
        assert name in catalog
        assert catalog[name]["external_effects"] is False
    assert "shell" not in catalog
    assert all(item.get("callable") is None or item["callable"].startswith("backend.") for item in catalog.values())
