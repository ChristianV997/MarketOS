from backend.organization.service_contract import ServiceCapability, ServiceContractRegistry


def test_contract_registry_fails_closed_for_unknown_and_live():
    registry = ServiceContractRegistry([ServiceCapability("x", "missing.module", "run", live_mutation_possible=True)])
    assert registry.validate_safe_to_call("unknown", "product")["status"] == "unsupported_service"
    result = registry.validate_safe_to_call("x", "product", live_action_requested=True)
    assert not result["allowed"] and "capability_may_mutate_live_system" in result["blocked_reasons"]


def test_contract_requires_explicit_dry_run():
    registry = ServiceContractRegistry([ServiceCapability("safe", "tests.test_service_contract", "plain", allowed_departments=["product"])])
    assert not registry.validate_safe_to_call("safe", "product")["allowed"]


def plain():
    return {"ok": True}
