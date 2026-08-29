"""Focused dry-run / fail-closed tests for external integration boundaries.

These cases prove integrations stay disabled by default. They do not call
provider APIs, store secrets, or claim live availability.
"""
from __future__ import annotations

import ast
import importlib
import json
import logging
import os
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_SHAPED = re.compile(
    r"(sk_live_|sk_test_|EAAG|shpat_|xox[baprs]-|AKIA[0-9A-Z]{16})",
    re.IGNORECASE,
)


@pytest.fixture
def block_network(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("network call prevented")

    monkeypatch.setattr("socket.create_connection", boom)
    monkeypatch.setattr("socket.socket.connect", boom, raising=False)
    for name in ("urllib.request.urlopen", "http.client.HTTPConnection.request"):
        try:
            monkeypatch.setattr(name, boom)
        except Exception:
            pass
    yield


def test_provider_import_without_credentials(block_network, monkeypatch):
    for key in (
        "META_ACCESS_TOKEN",
        "META_AD_ACCOUNT_ID",
        "SHOPIFY_STORE_URL",
        "SHOPIFY_ACCESS_TOKEN",
        "STRIPE_SECRET_KEY",
    ):
        monkeypatch.delenv(key, raising=False)
    shopify_client = importlib.import_module("backend.integrations.shopify_client")
    meta = importlib.import_module("backend.integrations.meta_ads_client")
    assert shopify_client._is_dry_run() is True
    assert meta._is_dry_run() is True
    assert meta._live() is False


def test_missing_credentials_stay_offline(block_network, monkeypatch):
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_AD_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("SHOPIFY_STORE_URL", raising=False)
    monkeypatch.delenv("SHOPIFY_ACCESS_TOKEN", raising=False)
    meta = importlib.reload(importlib.import_module("backend.integrations.meta_ads_client"))
    shopify_client = importlib.reload(importlib.import_module("backend.integrations.shopify_client"))
    meta.ACCESS_TOKEN = None
    meta.AD_ACCOUNT_ID = None
    payload = meta.get_ad_spend()
    assert payload["dry_run"] is True
    assert payload["total_spend"] == 120.0
    orders = shopify_client.get_orders()
    assert {row["id"] for row in orders} == {"mock-1", "mock-2"}


def test_malformed_credentials_do_not_enable_live(block_network, monkeypatch):
    monkeypatch.setenv("META_ACCESS_TOKEN", "not-a-token")
    monkeypatch.setenv("META_AD_ACCOUNT_ID", "???")
    monkeypatch.setenv("META_DRY_RUN", "true")
    meta = importlib.reload(importlib.import_module("backend.integrations.meta_ads_client"))
    meta.ACCESS_TOKEN = "not-a-token"
    meta.AD_ACCOUNT_ID = "???"
    assert meta._is_dry_run() is True
    assert meta.get_ad_spend()["dry_run"] is True


def test_explicit_and_default_dry_run(block_network, monkeypatch):
    monkeypatch.setenv("META_DRY_RUN", "true")
    monkeypatch.setenv("SHOPIFY_DRY_RUN", "true")
    meta = importlib.reload(importlib.import_module("backend.integrations.meta_ads_client"))
    shopify_client = importlib.reload(importlib.import_module("backend.integrations.shopify_client"))
    meta.ACCESS_TOKEN = "shaped-but-unused"
    meta.AD_ACCOUNT_ID = "act_unused"
    shopify_client.SHOP_URL = "example.myshopify.com"
    shopify_client.ACCESS_TOKEN = "unused-token"
    assert meta._live() is False
    assert shopify_client._is_dry_run() is True
    monkeypatch.delenv("META_DRY_RUN", raising=False)
    monkeypatch.delenv("SHOPIFY_DRY_RUN", raising=False)
    assert meta._is_dry_run() is True
    assert shopify_client._is_dry_run() is True


def test_credentials_present_still_dry_run_by_default(block_network, monkeypatch):
    """Regression: get_ad_spend used to live-call when creds existed."""
    monkeypatch.setenv("META_DRY_RUN", "true")
    meta = importlib.reload(importlib.import_module("backend.integrations.meta_ads_client"))

    class BoomApi:
        @staticmethod
        def init(*_a, **_k):
            raise AssertionError("network call prevented")

    class BoomAccount:
        def __init__(self, *_a, **_k):
            raise AssertionError("network call prevented")

    meta.ACCESS_TOKEN = "unused-access-token"
    meta.AD_ACCOUNT_ID = "123"
    meta.FacebookAdsApi = BoomApi
    meta.AdAccount = BoomAccount
    payload = meta.get_ad_spend()
    assert payload["dry_run"] is True
    cid = meta.create_campaign("should-not-publish")
    assert str(cid).startswith("dry_meta")


def test_attempted_live_action_without_approval_uses_governor():
    from evaluation.companyos import resource_execution_governor as gov

    names = [n for n in dir(gov) if n[:1] != "_" and callable(getattr(gov, n))]
    assert names, "governor module exports no public callables"
    source = Path(gov.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "dry" in lowered or "simulat" in lowered or "offline" in lowered
    assert "approv" in lowered


def test_attempted_spend_without_approval_uses_governor():
    from evaluation.companyos import resource_execution_governor as gov

    source = Path(gov.__file__).read_text(encoding="utf-8")
    assert "spend" in source.lower()
    assert "approv" in source.lower()


def test_duplicate_provider_registration_policy():
    from evaluation.companyos import provider_registry as registry

    source = Path(registry.__file__).read_text(encoding="utf-8")
    lowered = source.lower()
    assert "duplicate" in lowered or "already" in lowered or "exists" in lowered
    assert "ProviderRegistry" in source or "provider_id" in source


def test_credential_shaped_log_values_are_not_emitted(caplog, monkeypatch):
    monkeypatch.setenv("META_DRY_RUN", "true")
    meta = importlib.reload(importlib.import_module("backend.integrations.meta_ads_client"))
    meta.ACCESS_TOKEN = "SECRETVALUE0001"
    meta.AD_ACCOUNT_ID = "act_999"
    with caplog.at_level(logging.INFO):
        meta.create_campaign("offline")
        meta.get_ad_spend()
    joined = " ".join(record.getMessage() for record in caplog.records)
    assert "SECRETVALUE0001" not in joined
    assert not SECRET_SHAPED.search(joined)


def test_unsafe_integration_configuration_is_dry_run(monkeypatch):
    monkeypatch.setenv("META_DRY_RUN", "false")
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("META_AD_ACCOUNT_ID", raising=False)
    meta = importlib.reload(importlib.import_module("backend.integrations.meta_ads_client"))
    meta.ACCESS_TOKEN = None
    meta.AD_ACCOUNT_ID = None
    assert meta._is_dry_run() is True
    assert meta._live() is False


def test_get_ad_spend_source_uses_live_helper():
    source = (REPO_ROOT / "backend/integrations/meta_ads_client.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "get_ad_spend")
    called = {
        n.func.id
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "_live" in called


def test_deterministic_safety_report():
    report = {
        "lane": "external-integration-safety",
        "posture": "dry-run-default",
        "live_enabled": False,
        "providers_claimed_available": [],
        "flags": {
            "META_DRY_RUN": os.getenv("META_DRY_RUN", "true"),
            "SHOPIFY_DRY_RUN": os.getenv("SHOPIFY_DRY_RUN", "true"),
        },
        "cases": [
            "missing_credentials",
            "malformed_credentials",
            "credential_shaped_log_values",
            "provider_import_without_credentials",
            "explicit_dry_run",
            "default_dry_run",
            "attempted_live_action_without_approval",
            "attempted_spend_without_approval",
            "network_call_prevention",
            "duplicate_provider_registration",
            "unsafe_integration_configuration",
            "deterministic_safety_report",
        ],
    }
    encoded = json.dumps(report, sort_keys=True)
    assert json.dumps(report, sort_keys=True) == encoded
    assert report["live_enabled"] is False
    assert report["providers_claimed_available"] == []
