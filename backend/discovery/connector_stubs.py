from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .csv_ingestion import SUPPORTED_PARSERS


@dataclass
class EvidenceConnectorStub:
    connector_name: str
    parser_type: str
    source_type: str = "local_file"
    status: str = "disabled"
    network_required: bool = True
    credentials_required: bool = True
    mutation_possible: bool = False
    default_enabled: bool = False
    required_env_vars: list[str] = field(default_factory=list)
    output_format: str = "CSV local cache"
    parser_type_output: str = ""
    safety_contract: dict[str, Any] = field(default_factory=dict)
    blocked_reasons: list[str] = field(default_factory=lambda: ["future_connector_disabled", "no_live_acquisition_in_current_phase"])
    metadata: dict[str, Any] = field(default_factory=dict)
    def to_dict(self): return {key: getattr(self, key) for key in self.__dataclass_fields__}
    @classmethod
    def from_dict(cls, data): return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})


def _name(parser_type: str) -> str: return parser_type.replace("_csv", "") + "_export_connector"


def get_connector_stub(parser_type: str) -> EvidenceConnectorStub:
    if parser_type not in SUPPORTED_PARSERS: raise ValueError("unsupported_parser_type")
    return EvidenceConnectorStub(_name(parser_type), parser_type, required_env_vars=[f"MARKETOS_{parser_type.upper()}_READ_ONLY"], parser_type_output=parser_type, safety_contract={"no_run_method": True, "requires_manual_approval": True, "read_only_output": True, "network_access": "blocked"})


def list_connector_stubs() -> list[EvidenceConnectorStub]: return [get_connector_stub(parser) for parser in sorted(SUPPORTED_PARSERS)]


def validate_connector_stub_disabled(stub: EvidenceConnectorStub) -> dict[str, Any]:
    reasons = list(stub.blocked_reasons)
    if stub.default_enabled: reasons.append("default_enabled_forbidden")
    if stub.network_required: reasons.append("network_required")
    if stub.credentials_required: reasons.append("credentials_required")
    if stub.mutation_possible: reasons.append("mutation_possible")
    if stub.status != "disabled": reasons.append("stub_not_disabled")
    return {"allowed": False, "status": "blocked", "connector_name": stub.connector_name, "blocked_reasons": list(dict.fromkeys(reasons))}
