from backend.organization.service_adapters import execute_governed_service
from backend.organization.service_contract import ServiceCapability, ServiceContractRegistry


def safe_stub(*, dry_run: bool = True, read_only: bool = True, value: int = 1):
    return {"value": value, "dry_run": dry_run}


def failing_stub(*, dry_run: bool = True, read_only: bool = True):
    raise RuntimeError("boom")


def test_unavailable_and_live_inputs_fail_closed():
    product = execute_governed_service("product_research", "product", {"product_name": "Bottle", "category": "home"}, "w")
    assert product.status == "completed" and product.output["provenance"]["market_data"] == "not_connected"
    assert execute_governed_service("future_unaudited", "product", {}, "w").status == "unsupported_service"
    assert execute_governed_service("product_research", "product", {"confirm_live": True}, "w").status == "blocked"


def test_new_mvp_services_are_connected():
    customer = execute_governed_service("customer_intelligence", "growth", {"business_type": "Brand", "vertical": "car_sales"}, "w")
    profit = execute_governed_service("profit_stack_advisor", "finance", {"business_name": "Brand"}, "w")
    assert customer.status == "completed" and customer.dry_run is True
    assert profit.status == "completed" and profit.dry_run is True


def test_safe_stub_executes_and_failure_is_structured(monkeypatch):
    import sys
    module = sys.modules[__name__]
    registry = ServiceContractRegistry([ServiceCapability("stub", module.__name__, "safe_stub", allowed_departments=["product"])])
    result = execute_governed_service("stub", "product", {"value": 3}, "w", registry=registry)
    assert result.status == "completed" and result.dry_run is True
    failing = ServiceContractRegistry([ServiceCapability("fail", module.__name__, "failing_stub", allowed_departments=["product"])])
    assert execute_governed_service("fail", "product", {}, "w", registry=failing).status == "service_execution_failed"
