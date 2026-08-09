from __future__ import annotations

from copy import deepcopy
from backend.workflows.workflow_safety import validate_workflow_payload_safe
from .action_catalog import get_cockpit_action_catalog


def validate_cockpit_payload_safe(action_type: str, payload: dict) -> dict:
    catalog = get_cockpit_action_catalog()
    if action_type not in catalog:
        return {"safe": False, "sanitized_payload": {}, "blocked_reasons": ["unknown_action_type"], "warnings": []}
    safe_payload = deepcopy(payload or {})
    blocked = []
    warnings = []
    allowed = set(catalog[action_type].get("allowed_payload_keys", []))
    for key in safe_payload:
        if allowed and key not in allowed:
            blocked.append(f"unknown_payload_key:{key}")
    workflow = validate_workflow_payload_safe(safe_payload)
    blocked.extend(workflow.get("blocked_reasons", []))

    def scan(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in ("credential", "secret", "token", "password", "api_key")):
                    blocked.append(f"secret_like_payload:{path}{key}")
                if lowered in {"shell", "command", "python", "code", "exec", "execute"} and child:
                    blocked.append(f"arbitrary_execution_field:{path}{key}")
                scan(child, f"{path}{key}.")
        elif isinstance(value, list):
            if len(value) > 100: blocked.append(f"list_limit:{path}")
            for index, child in enumerate(value): scan(child, f"{path}{index}.")
        elif isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
            blocked.append(f"external_url:{path}")
    scan(safe_payload)
    return {"safe": not blocked, "sanitized_payload": safe_payload, "blocked_reasons": sorted(set(blocked)), "warnings": warnings}
