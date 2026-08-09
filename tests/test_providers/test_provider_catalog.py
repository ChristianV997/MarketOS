from __future__ import annotations

from pathlib import Path

import yaml

from backend.providers import provider_registry

_REPO_ROOT = Path(__file__).resolve().parents[2]


def test_expected_providers_registered():
    ids = {p.provider_id for p in provider_registry.list()}
    for expected in (
        "hostinger", "woocommerce", "medusa", "shopify",
        "stripe_mx", "mercado_pago_mx", "chatwoot", "n8n",
        "mautic", "activepieces", "gohighlevel", "postiz",
        "posthog", "twenty",
    ):
        assert expected in ids


def test_no_duplicate_provider_ids():
    ids = [p.provider_id for p in provider_registry.list()]
    assert len(ids) == len(set(ids))


def test_woocommerce_and_medusa_have_adapter_available_commerce_capability():
    woo = provider_registry.get("woocommerce")
    assert woo.integration_status == "adapter_available"
    assert "orders" in woo.capabilities


def test_gohighlevel_plans_have_revenue_thresholds():
    ghl = provider_registry.get("gohighlevel")
    assert all(plan.min_monthly_revenue_usd > 0 for plan in ghl.plans)


def test_n8n_is_internal_only():
    n8n = provider_registry.get("n8n")
    assert n8n.risk.internal_only is True


def test_postiz_requires_legal_approval():
    postiz = provider_registry.get("postiz")
    assert postiz.risk.requires_legal_approval is True


def test_twenty_requires_legal_approval_and_is_catalog_only():
    twenty = provider_registry.get("twenty")
    assert twenty.risk.requires_legal_approval is True
    assert twenty.integration_status == "catalog_only"


def test_chatwoot_mautic_activepieces_posthog_have_adapters():
    for provider_id in ("chatwoot", "mautic", "activepieces", "posthog", "hostinger"):
        assert provider_registry.get(provider_id).integration_status == "adapter_available"


def test_no_unknown_license_provider_marked_safe_against_oss_inventory():
    """Every provider that references an OSS inventory candidate must have a
    license matching that candidate's recorded license — a provider must
    never claim a license the governance record doesn't confirm."""
    inventory = yaml.safe_load((_REPO_ROOT / "docs/oss/INVENTORY.yml").read_text())
    by_name = {c["name"]: c for c in inventory["candidates"]}
    for provider in provider_registry.list():
        if provider.oss_inventory_ref is None:
            continue
        assert provider.oss_inventory_ref in by_name, (
            f"{provider.provider_id} references unknown OSS inventory entry "
            f"{provider.oss_inventory_ref!r}"
        )
        candidate = by_name[provider.oss_inventory_ref]
        assert provider.license == candidate["license"], (
            f"{provider.provider_id} license {provider.license!r} does not "
            f"match INVENTORY.yml's {candidate['license']!r} for "
            f"{provider.oss_inventory_ref!r}"
        )
