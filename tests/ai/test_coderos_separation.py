"""CoderOS separation regression tests.

Proves the AI-chat-operator reconciliation lane's requirement: MarketOS must
not import a live CoderOS runtime, and no CoderOS-shaped metadata (capability
record entries or a "work-order plan" payload) can ever carry live-action
authority. This test suite does not create a second CoderOS runtime or
safety authority -- it exercises the two that already exist:
``backend.adapters.coderos_readonly`` (the in-repo read-only adapter) and
``scripts.ai.native_agent_capability`` (this lane's sanitized command-
presence catalog).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from backend.adapters.coderos_readonly import SafetySummary, _default_safety_summary
from scripts.ai.native_agent_capability import build_capability_record, probe_agent

REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_RUNTIME_DIRS = ("backend", "core", "orchestrator", "services", "api", "evaluation")


def _imports_coderos(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any("coderos" in alias.name.lower() for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if "coderos" in node.module.lower():
                return True
    return False


def test_marketos_core_runtime_never_imports_coderos():
    """CoderOS absence must never break MarketOS: nothing outside the
    adapter's own file imports it."""
    offenders: list[str] = []
    for directory in CORE_RUNTIME_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if path == REPO_ROOT / "backend" / "adapters" / "coderos_readonly.py":
                continue
            if "test" in path.name:
                continue
            if _imports_coderos(path):
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], f"core runtime modules import CoderOS: {offenders}"


def test_coderos_adapter_safety_summary_fails_closed_on_any_live_claim():
    """The adapter's own SafetySummary is a structural guarantee, not a
    report -- constructing it with any live/mutating field set must raise."""
    baseline = _default_safety_summary().to_dict()
    for live_field in (
        "network_calls", "credentials_loaded", "external_mutation", "model_calls",
        "provider_calls", "sdk_used", "raw_stdout_exposed", "raw_stderr_exposed",
        "artifact_writes", "background_process", "automatic_retry",
    ):
        tampered = dict(baseline)
        tampered[live_field] = True
        with pytest.raises(ValueError, match="live/mutating/retaining"):
            SafetySummary(**tampered)


def test_coderos_capability_entry_never_authorizes_live_actions():
    record = build_capability_record(commands=["coderos"])
    entry = record["coderos"]
    assert entry["can_authorize_live_actions"] is False
    assert entry["marketos_runtime_import"] == "never"
    assert record["credentials_read"] is False
    assert record["account_ids_stored"] is False


def test_coderos_probe_never_reads_credentials_or_stores_account_ids():
    entry = probe_agent("coderos")
    assert entry["credential_state"] == "not_read"
    assert entry["account_id_stored"] is False


@pytest.mark.parametrize(
    "work_order_plan",
    [
        {"action": "deploy", "environment": "production", "approved": True},
        {"action": "create_payment", "amount": 500, "currency": "USD"},
        {"action": "launch_ad_campaign", "budget": 1000},
        {"action": "place_order", "sku": "widget-1", "quantity": 10},
        {"action": "send_customer_message", "channel": "email", "body": "hi"},
    ],
)
def test_work_order_plan_metadata_cannot_authorize_live_actions(work_order_plan):
    """A CoderOS-shaped 'work-order plan' payload is operator-supplied
    metadata, not an authority -- feeding it through the capability record's
    only ingestion path (``observed`` evidence) must never upgrade any
    state, since it carries no accompanying evidence for any field."""
    observed = {"coderos": {"enabled": "enabled", **work_order_plan}}
    record = build_capability_record(commands=["coderos"], observed=observed)
    entry = record["coderos"]
    assert entry["enabled"] == "not_run"
    assert "enabled" in entry.get("rejected_claims", [])
    assert entry["can_authorize_live_actions"] is False


def test_work_order_plan_with_fabricated_evidence_key_is_still_rejected():
    """Even a claim that *looks* like it carries evidence (a truthy
    ``*_evidence`` sibling key) must not authorize deployment, payment,
    advertising, order, or messaging capability -- those are not fields
    this capability record recognizes as upgradeable at all."""
    observed = {
        "coderos": {
            "deploy_authorized": True,
            "deploy_authorized_evidence": "operator said so",
        }
    }
    record = build_capability_record(commands=["coderos"], observed=observed)
    entry = record["coderos"]
    assert "deploy_authorized" not in entry
    assert entry["can_authorize_live_actions"] is False
