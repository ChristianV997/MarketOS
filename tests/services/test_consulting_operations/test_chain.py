"""Tests for consulting chain readiness."""
from __future__ import annotations

import pytest

from services.consulting_operations.chain import evaluate_consulting_chain


def test_chain_success():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product", "id": "1"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={"price": [100, 200], "margin": {"low": 10, "high": 20}},
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"state": "present"}, "doc2": {"state": "missing"}},
    )
    assert result.status == "ready"
    assert result.stage == "delivery"
    assert "deliverable" in result.payload


def test_chain_missing_stage_blocks():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={},
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"state": "present"}},
    )
    assert result.status == "blocked"
    assert result.stage == "economics"


def test_chain_workspace_identity_mismatch():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-DIFFERENT",
            "owner": "owner-1",
        },
        raw_economics={"price": [100, 200]},
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"state": "present"}},
    )
    assert result.status == "failed"
    assert "workspace_identity_mismatch" in result.reasons


def test_chain_unsafe_leakage_rejected():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={"price": [100, 200]},
        raw_portfolio={"internal_prompt": "secret"},
        raw_evidence={"doc1": {"state": "present"}},
    )
    assert result.status == "error"
    assert any("Workspace isolation violation" in r for r in result.reasons)


def test_chain_economics_scalar_rejected():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={"price": 150},  # Must be range/dict/list
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"state": "present"}},
    )
    assert result.status == "failed"
    assert "economics_must_be_ranges" in result.reasons

def test_chain_normalizes_evidence_status_to_state():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product", "id": "1"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={"price": [100, 200], "margin": {"low": 10, "high": 20}},
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"status": "present"}, "doc2": {"status": "missing"}},
    )
    assert result.status == "ready"
    assert result.stage == "delivery"

def test_chain_rejects_invalid_evidence_state():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[{"type": "product", "id": "1"}],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={"price": [100, 200], "margin": {"low": 10, "high": 20}},
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"status": "fake_state"}},
    )
    assert result.status == "failed"
    assert "invalid_evidence_state_fake_state" in result.reasons

class MockOffer:
    def __init__(self, type, id):
        self.type = type
        self.id = id

def test_chain_accepts_protocol_offers():
    result = evaluate_consulting_chain(
        workspace_id="ws-1",
        engagement_id="eng-1",
        raw_offers=[MockOffer("service", "2")],
        raw_engagement={
            "engagement_id": "eng-1",
            "package_id": "pkg-1",
            "workspace_id": "ws-1",
            "owner": "owner-1",
        },
        raw_economics={"price": [100, 200], "margin": {"low": 10, "high": 20}},
        raw_portfolio={"summary": "test"},
        raw_evidence={"doc1": {"status": "present"}},
    )
    assert result.status == "ready"
    assert result.stage == "delivery"
