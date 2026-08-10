from backend.providers.capabilities import list_capability_definitions
from backend.providers.vendor_catalog import list_vendor_capability_records


def test_every_capability_has_owner_and_route_or_explicit_gap() -> None:
    capabilities = list_capability_definitions()
    records = list_vendor_capability_records()
    assert capabilities
    assert all(item.owning_department and item.default_agent_role for item in capabilities)
    routed = {item.capability_id for item in records}
    assert {item.capability_id for item in capabilities} <= routed


def test_use_now_routes_are_not_live_mutation_routes() -> None:
    use_now = [item for item in list_vendor_capability_records() if item.use_stage.value == "use_now"]
    assert use_now
    assert all(item.integration_mode.value for item in use_now)
    assert all(not item.live_mutation_risk for item in use_now)
