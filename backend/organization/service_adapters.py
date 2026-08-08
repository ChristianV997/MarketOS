from __future__ import annotations

import importlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from evaluation import ProductCandidate, SupplierOffer, calculate_unit_economics
from core.creative.generator import generate_creative

from .service_contract import ServiceCapability, ServiceExecutionResult, ServiceContractRegistry, get_service_contract_registry


_SERVICE_TARGETS = {
    "product_research": ("services.product_research.audit", "run_product_audit"),
    "unit_economics": ("services.unit_economics.analyzer", "run_unit_economics"),
    "creative_growth": ("services.creative_growth.plan", "build_creative_growth_plan"),
    "customer_intelligence": ("services.customer_intelligence.sprint", "build_customer_intelligence_sprint"),
    "profit_stack_advisor": ("services.profit_stack_advisor.advisor", "run_profit_stack_advisor"),
}
_LIVE_INPUT_KEYS = {"live", "confirm_live", "live_action_requested", "execute_live", "send_message", "place_order"}


def _fallback_unit_economics(*, dry_run: bool = True, read_only: bool = True, product: dict[str, Any], offer: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    if not dry_run or not read_only:
        raise PermissionError("unit economics fallback is read-only")
    return calculate_unit_economics(ProductCandidate(**product), SupplierOffer(**offer) if offer else None)


def _fallback_creative_growth(*, dry_run: bool = True, read_only: bool = True, product: str = "", angle: str = "", **kwargs: Any) -> dict[str, Any]:
    if not dry_run or not read_only:
        raise PermissionError("creative fallback is read-only")
    return {"script": generate_creative(product, angle), "product": product, "angle": angle}


def default_capabilities() -> list[ServiceCapability]:
    allowed = {
        "product_research": ["strategy", "product"], "unit_economics": ["product", "finance"],
        "creative_growth": ["creative", "growth"], "customer_intelligence": ["strategy", "growth"],
        "profit_stack_advisor": ["finance", "strategy"],
    }
    fallback = {
        "unit_economics": ("backend.organization.service_adapters", "_fallback_unit_economics"),
        "creative_growth": ("backend.organization.service_adapters", "_fallback_creative_growth"),
    }
    items: list[ServiceCapability] = []
    for service_name, (module_path, function_name) in _SERVICE_TARGETS.items():
        using_verified_fallback = False
        primary_available = False
        try:
            importlib.import_module(module_path)
            primary_available = True
        except ImportError:
            pass
        if service_name in fallback:
            if not primary_available:
                module_path, function_name = fallback[service_name]
                using_verified_fallback = True
        items.append(ServiceCapability(service_name=service_name, module_path=module_path, function_name=function_name,
                                       read_only=True, dry_run_required=True, live_mutation_possible=primary_available and not using_verified_fallback,
                                       external_io_possible=service_name == "creative_growth", allowed_departments=allowed[service_name],
                                       metadata={"verified": using_verified_fallback, "requires_explicit_audit": not using_verified_fallback}))
    return items


def _safe(value: Any) -> Any:
    if hasattr(value, "to_dict"): return _safe(value.to_dict())
    if is_dataclass(value): return _safe(asdict(value))
    if isinstance(value, dict): return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)): return [_safe(v) for v in value]
    try: json.dumps(value); return value
    except TypeError: return str(value)


def execute_governed_service(service_name: str, department_id: str, inputs: dict[str, Any], workspace=None,
                             live_action_requested: bool = False, registry: ServiceContractRegistry | None = None) -> ServiceExecutionResult:
    registry = registry or get_service_contract_registry()
    if not isinstance(inputs, dict):
        return ServiceExecutionResult(service_name, "service_execution_failed", dry_run=True, errors=["inputs_must_be_object"])
    if any(bool(inputs.get(key)) for key in _LIVE_INPUT_KEYS) or inputs.get("dry_run") is False or inputs.get("read_only") is False:
        return ServiceExecutionResult(service_name, "blocked", dry_run=True, blocked_reasons=["live_execution_forbidden_in_governance_loop"])
    validation = registry.validate_safe_to_call(service_name, department_id, live_action_requested)
    if not validation.get("allowed"):
        return ServiceExecutionResult(service_name, validation.get("status", "blocked"), dry_run=True, blocked_reasons=validation.get("blocked_reasons", []), metadata={"validation": validation})
    capability = registry.get(service_name)
    try:
        module = importlib.import_module(capability.module_path)
        function = getattr(module, capability.function_name)
    except (ImportError, AttributeError):
        return ServiceExecutionResult(service_name, "service_module_unavailable", dry_run=True, blocked_reasons=["service_module_unavailable"])
    try:
        safe_inputs = {key: value for key, value in inputs.items() if key not in {"live", "confirm_live", "live_action_requested", "execute_live", "send_message", "place_order", "dry_run", "read_only"}}
        safe_inputs.update({"dry_run": True, "read_only": True})
        result = function(**safe_inputs)
        serialized = _safe(result)
        experiment_id = serialized.get("experiment_id") if isinstance(serialized, dict) else None
        return ServiceExecutionResult(service_name, "completed", serialized, experiment_id, True, metadata={"capability": capability.to_dict()})
    except Exception as exc:
        return ServiceExecutionResult(service_name, "service_execution_failed", dry_run=True, errors=[type(exc).__name__], metadata={"capability": capability.to_dict()})
