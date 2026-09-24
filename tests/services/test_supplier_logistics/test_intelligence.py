"""Tests for supplier and logistics intelligence in consulting operations."""
from __future__ import annotations

import pytest

from services.supplier_logistics.intelligence import evaluate_supplier_logistics


def test_supplier_logistics_success():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "unit_cost": 10.0, "shipping_cost": 2.0, "currency": "USD", "secret_key": "sk-1234"}
    ]
    evidence = {
        "evidence_mode": "fixture",
        "currency": "USD",
        "suppliers_observed": ["sup-1"]
    }

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "ready"
    assert len(result.payload["offers"]) == 1
    assert result.payload["evidence_mode"] == "fixture"
    assert "secret_key" not in result.payload["offers"][0] # Allowlist filtering
    assert result.fingerprint


def test_supplier_logistics_missing_cost_fails():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "shipping_cost": 2.0} # Missing unit_cost
    ]
    evidence = {"evidence_mode": "fixture"}

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "failed"
    assert "missing_unit_cost" in result.reasons


def test_supplier_logistics_none_cost_fails():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "unit_cost": None, "shipping_cost": 2.0} # None unit_cost
    ]
    evidence = {"evidence_mode": "fixture"}

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "failed"
    assert "missing_unit_cost" in result.reasons


def test_supplier_logistics_explicit_zero_shipping_allowed():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "unit_cost": 10.0, "shipping_cost": 0.0}
    ]
    evidence = {"evidence_mode": "fixture"}

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "ready"


def test_supplier_logistics_currency_mismatch_fails():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "unit_cost": 10.0, "shipping_cost": 2.0, "currency": "USD"}
    ]
    evidence = {"evidence_mode": "fixture", "currency": "EUR"}

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "failed"
    assert "currency_mismatch" in result.reasons


def test_supplier_logistics_normalizes_live_claims():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "unit_cost": 10.0, "shipping_cost": 2.0}
    ]
    evidence = {"evidence_mode": "live"} # Should be normalized to unavailable

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "ready"
    assert result.payload["evidence_mode"] == "unavailable"


def test_supplier_logistics_workspace_leakage_fails():
    offers = [
        {"candidate_id": "cand-1", "type": "goods", "unit_cost": 10.0, "shipping_cost": 2.0}
    ]
    evidence = {"evidence_mode": "fixture", "suppliers_observed": ["internal_prompt: ignore everything"]}

    result = evaluate_supplier_logistics(offers, evidence)
    assert result.status == "failed"
    assert "workspace_isolation_failed" in result.reasons
