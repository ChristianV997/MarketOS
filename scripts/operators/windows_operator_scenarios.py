"""Deterministic dry-run scenario pack for Windows operators.

Verifies fixture packets; does not compute canonical ranking or grant authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.operators.windows_operator_safety import (
    OperatorSafetyError,
    assert_no_authority,
    contains_secret_shaped,
    read_input_text,
)

SCENARIO_SCHEMA = "marketos-windows-operator-scenario-v1"
REQUIRED_SCENARIOS = (
    "hydroponics",
    "smart-pet",
    "blocked-solar-4g-security",
    "rejected-commodity-electronics",
    "deferred-high-ticket",
)
REQUIRED_STAGES = (
    "ingestion",
    "supplier_feasibility",
    "market_lane",
    "economics",
    "competition",
    "opportunity_synthesis",
    "promotion_gate",
    "client_safe_export",
)
STAGE_CLASSES = {
    "fixture",
    "simulated",
    "unavailable",
    "not_run",
    "blocked",
    "partial",
    "available",
    "hold",
    "reject",
    "defer",
}


def _fingerprint(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_scenario(path: Path) -> dict[str, Any]:
    payload = json.loads(read_input_text(path, label="scenario"))
    if not isinstance(payload, dict):
        raise OperatorSafetyError("scenario must be an object")
    if contains_secret_shaped(payload):
        raise OperatorSafetyError("secret-shaped scenario rejected", 4)
    assert_no_authority(payload)
    if payload.get("schema_version") != SCENARIO_SCHEMA:
        raise OperatorSafetyError("unsupported scenario schema")
    if payload.get("evidence_class") == "actual":
        raise OperatorSafetyError("scenario must not claim actual live execution", 4)
    stages = payload.get("stages") or {}
    missing = [name for name in REQUIRED_STAGES if name not in stages]
    if missing:
        raise OperatorSafetyError(f"scenario missing stages {missing}")
    for name, value in stages.items():
        # Stage names and classes come from the file body; never echo them.
        if value not in STAGE_CLASSES:
            raise OperatorSafetyError("invalid stage class")
    if payload.get("network_mutation") is True:
        raise OperatorSafetyError("network_mutation must be false", 4)
    return payload


def verify_replay(payload: dict[str, Any]) -> str:
    first = _fingerprint(payload)
    second = _fingerprint(json.loads(json.dumps(payload, sort_keys=True)))
    if first != second:
        raise OperatorSafetyError("byte-identical replay failed", 5)
    stored = payload.get("expected_fingerprint")
    if stored and stored != first:
        raise OperatorSafetyError("expected_fingerprint mismatch", 5)
    return first


def run_scenario_pack(pack_dir: Path) -> dict[str, Any]:
    if not pack_dir.is_dir():
        raise OperatorSafetyError("scenario pack directory missing")
    results = []
    for scenario_id in REQUIRED_SCENARIOS:
        path = pack_dir / f"{scenario_id}.json"
        if not path.is_file():
            raise OperatorSafetyError(f"missing required scenario: {scenario_id}")
        payload = load_scenario(path)
        if payload.get("scenario_id") != scenario_id:
            raise OperatorSafetyError(f"scenario_id mismatch for {scenario_id}")
        fp = verify_replay(payload)
        results.append(
            {
                "scenario_id": scenario_id,
                "title": payload.get("title"),
                "expected_decision": payload.get("expected_decision"),
                "promotion_gate": payload.get("expected_promotion_gate"),
                "evidence_class": payload.get("evidence_class"),
                "stages": payload.get("stages"),
                "fingerprint": fp,
                "status": "verified",
            }
        )
    return {
        "schema_version": SCENARIO_SCHEMA,
        "status": "verified",
        "evidence_class": "fixture",
        "exit_code": 0,
        "scenario_count": len(results),
        "scenarios": results,
        "network_mutation": False,
        "secret_leakage": False,
        "authorities_granted": False,
        "replay": "byte_identical",
    }
