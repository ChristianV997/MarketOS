from backend.organization.service_adapters import execute_governed_service
from backend.organization.service_contract import ServiceCapability, ServiceContractRegistry


def safe_stub(*, dry_run: bool = True, read_only: bool = True, value: int = 1):
    return {"value": value, "dry_run": dry_run}


def failing_stub(*, dry_run: bool = True, read_only: bool = True):
    raise RuntimeError("boom")


def test_unavailable_and_live_inputs_fail_closed():
    assert execute_governed_service("product_research", "product", {}, "w").status == "service_module_unavailable"
    assert execute_governed_service("product_research", "product", {"confirm_live": True}, "w").status == "blocked"


def test_safe_stub_executes_and_failure_is_structured(monkeypatch):
    import sys
    module = sys.modules[__name__]
    registry = ServiceContractRegistry([ServiceCapability("stub", module.__name__, "safe_stub", allowed_departments=["product"])])
    result = execute_governed_service("stub", "product", {"value": 3}, "w", registry=registry)
    assert result.status == "completed" and result.dry_run is True
    failing = ServiceContractRegistry([ServiceCapability("fail", module.__name__, "failing_stub", allowed_departments=["product"])])
    assert execute_governed_service("fail", "product", {}, "w", registry=failing).status == "service_execution_failed"
