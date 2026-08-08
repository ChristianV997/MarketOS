from __future__ import annotations

import importlib
import inspect
import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ServiceCapability:
    service_name: str
    module_path: str
    function_name: str
    read_only: bool = True
    dry_run_required: bool = True
    live_mutation_possible: bool = False
    external_io_possible: bool = False
    allowed_departments: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


@dataclass
class ServiceExecutionResult:
    service_name: str
    status: str
    output: Any = None
    experiment_id: str | None = None
    dry_run: bool = True
    blocked_reasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {key: getattr(self, key) for key in self.__dataclass_fields__}


class ServiceContractRegistry:
    def __init__(self, capabilities: list[ServiceCapability] | None = None) -> None:
        self._items: dict[str, ServiceCapability] = {}
        self._lock = threading.RLock()
        for capability in capabilities or []:
            self.register(capability)

    def register(self, capability: ServiceCapability) -> ServiceCapability:
        if not isinstance(capability, ServiceCapability):
            raise TypeError("capability must be ServiceCapability")
        with self._lock:
            self._items[capability.service_name] = capability
        return capability

    def get(self, service_name: str) -> ServiceCapability | None:
        return self._items.get(service_name)

    def list(self) -> list[ServiceCapability]:
        return list(self._items.values())

    def allowed_for_department(self, service_name: str, department_id: str) -> bool:
        capability = self.get(service_name)
        return bool(capability and (not capability.allowed_departments or department_id in capability.allowed_departments))

    def validate_safe_to_call(self, service_name: str, department_id: str, live_action_requested: bool = False) -> dict[str, Any]:
        capability = self.get(service_name)
        if capability is None:
            return {"allowed": False, "status": "unsupported_service", "blocked_reasons": ["unsupported_service"], "service_name": service_name}
        blocked: list[str] = []
        if live_action_requested:
            blocked.append("live_action_forbidden")
        if capability.live_mutation_possible:
            blocked.append("capability_may_mutate_live_system")
        if not capability.read_only:
            blocked.append("capability_not_read_only")
        if capability.allowed_departments and department_id not in capability.allowed_departments:
            blocked.append("service_not_allowed_for_department")
        try:
            module = importlib.import_module(capability.module_path)
            function = getattr(module, capability.function_name)
        except (ImportError, AttributeError):
            reasons = [*blocked, "service_module_unavailable"]
            return {"allowed": False, "status": "blocked" if blocked else "service_module_unavailable", "blocked_reasons": reasons, "service_name": service_name, "capability": capability.to_dict()}
        except Exception as exc:
            reasons = [*blocked, "service_module_unavailable"]
            return {"allowed": False, "status": "blocked" if blocked else "service_module_unavailable", "blocked_reasons": reasons, "service_name": service_name, "error_type": type(exc).__name__, "capability": capability.to_dict()}
        if capability.dry_run_required:
            try:
                parameters = inspect.signature(function).parameters
            except (TypeError, ValueError):
                return {"allowed": False, "status": "blocked", "blocked_reasons": ["dry_run_contract_uninspectable"], "service_name": service_name, "capability": capability.to_dict()}
            if "dry_run" not in parameters and "read_only" not in parameters and not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                blocked.append("dry_run_contract_missing")
        return {"allowed": not blocked, "status": "ready" if not blocked else "blocked", "blocked_reasons": blocked, "service_name": service_name, "capability": capability.to_dict()}


def default_service_contract_registry() -> ServiceContractRegistry:
    from .service_adapters import default_capabilities
    return ServiceContractRegistry(default_capabilities())


_registry: ServiceContractRegistry | None = None
_registry_lock = threading.Lock()


def get_service_contract_registry() -> ServiceContractRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = default_service_contract_registry()
    return _registry
