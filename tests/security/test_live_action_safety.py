"""Tests for live-action safety gates, dry-run invariants, and kill switches."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import app
from backend.security.auth import AuthenticatedActor, register_test_token
from backend.security.live_action_gate import (
    LiveActionRequest,
    evaluate_live_action_gate,
)


@pytest.fixture
def client():
    return TestClient(app)


def test_dry_run_always_allowed_safely():
    actor = AuthenticatedActor("op1", "operator", frozenset({"*"}))
    req = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        idempotency_key="dry_key_1234",
        dry_run=True,
    )
    verdict = evaluate_live_action_gate(req)
    assert verdict.allowed is True
    assert verdict.dry_run is True
    assert verdict.status == "dry_run_simulated"


def test_live_action_blocked_without_global_enable(monkeypatch):
    monkeypatch.delenv("MARKETOS_ENABLE_LIVE_ACTIONS", raising=False)
    actor = AuthenticatedActor("op1", "operator", frozenset({"*"}))
    req = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        idempotency_key="live_key_12345",
        approval_id="appr_123",
        run_id="run_123",
        dry_run=False,
    )
    verdict = evaluate_live_action_gate(req)
    assert verdict.allowed is False
    assert "live_actions_globally_disabled" in verdict.blockers


def test_live_action_requires_approval_and_idempotency(monkeypatch):
    monkeypatch.setenv("MARKETOS_ENABLE_LIVE_ACTIONS", "true")
    actor = AuthenticatedActor("op1", "operator", frozenset({"*"}))

    # Missing approval_id
    req_no_appr = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        idempotency_key="live_key_12345",
        approval_id=None,
        run_id="run_123",
        dry_run=False,
    )
    verdict = evaluate_live_action_gate(req_no_appr)
    assert verdict.allowed is False
    assert "approval_id_required_for_live_action" in verdict.blockers

    # Missing idempotency key
    req_no_idem = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        idempotency_key="",
        approval_id="appr_123",
        run_id="run_123",
        dry_run=False,
    )
    verdict_idem = evaluate_live_action_gate(req_no_idem)
    assert verdict_idem.allowed is False
    assert "valid_idempotency_key_required_min_8_chars" in verdict_idem.blockers


def test_live_action_requires_run_id(monkeypatch):
    monkeypatch.setenv("MARKETOS_ENABLE_LIVE_ACTIONS", "true")
    actor = AuthenticatedActor("op1", "operator", frozenset({"*"}))

    req_no_run = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        idempotency_key="live_key_12345",
        approval_id="appr_123",
        run_id=None,
        dry_run=False,
    )
    verdict = evaluate_live_action_gate(req_no_run)
    assert verdict.allowed is False
    assert "run_id_required_for_live_action" in verdict.blockers


def test_kill_switch_blocks_action(monkeypatch):
    monkeypatch.setenv("MARKETOS_ENABLE_LIVE_ACTIONS", "true")
    monkeypatch.setenv("MARKETOS_KILL_SWITCH", "true")

    actor = AuthenticatedActor("op1", "operator", frozenset({"*"}))
    req = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        idempotency_key="live_key_12345",
        approval_id="appr_123",
        run_id="run_123",
        dry_run=False,
    )
    verdict = evaluate_live_action_gate(req)
    assert verdict.allowed is False
    assert "kill_switch_engaged" in verdict.blockers


def test_budget_ceiling_enforcement(monkeypatch):
    monkeypatch.setenv("MARKETOS_ENABLE_LIVE_ACTIONS", "true")
    monkeypatch.setenv("MARKETOS_MAX_LIVE_BUDGET_USD", "50.0")

    actor = AuthenticatedActor("op1", "operator", frozenset({"*"}))
    req = LiveActionRequest(
        action_type="ad_spend",
        workspace_id="default",
        actor=actor,
        budget_amount=200.0,
        idempotency_key="live_key_12345",
        approval_id="appr_123",
        run_id="run_123",
        dry_run=False,
    )
    verdict = evaluate_live_action_gate(req)
    assert verdict.allowed is False
    assert any("budget_exceeds_ceiling" in b for b in verdict.blockers)


def test_commerce_publish_endpoint_live_gate(client, monkeypatch):
    register_test_token("tok_op", actor_id="operator", role="operator")
    headers = {"Authorization": "Bearer tok_op"}

    # Dry-run publish succeeds
    resp_dry = client.post(
        "/commerce/publish",
        json={"dry_run": True, "bundle": {"topic": "test", "angle": "hook"}},
        headers=headers,
    )
    assert resp_dry.status_code == 200
    assert resp_dry.json().get("dry_run") is True

    # Live publish without confirm_live fails
    resp_live_unconfirmed = client.post(
        "/commerce/publish",
        json={"dry_run": False, "bundle": {"topic": "test"}},
        headers=headers,
    )
    assert resp_live_unconfirmed.status_code == 200
    assert "live_publishing_requires_confirm_live" in resp_live_unconfirmed.json().get("reasons", [])

    # Live publish without live approval / gate approval is blocked by gate
    resp_live = client.post(
        "/commerce/publish",
        json={
            "dry_run": False,
            "confirm_live": True,
            "bundle": {"topic": "test"},
        },
        headers=headers,
    )
    assert resp_live.status_code == 200
    data = resp_live.json()
    assert data.get("published") is False
    assert "approval_id_required_for_live_action" in data.get("reasons", []) or "live_actions_globally_disabled" in data.get("reasons", [])
