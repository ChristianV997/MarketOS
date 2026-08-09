from __future__ import annotations

import pytest

from backend.providers.registry import ProviderRegistry
from backend.providers.schemas import Provider


def _provider(provider_id: str, category: str = "commerce_platform") -> Provider:
    return Provider(provider_id=provider_id, name=provider_id.title(), category=category)


def test_register_and_get():
    registry = ProviderRegistry()
    registry.register(_provider("acme"))
    assert registry.get("acme").provider_id == "acme"


def test_register_duplicate_raises():
    registry = ProviderRegistry()
    registry.register(_provider("acme"))
    with pytest.raises(ValueError):
        registry.register(_provider("acme"))


def test_get_unknown_raises():
    registry = ProviderRegistry()
    with pytest.raises(KeyError):
        registry.get("does-not-exist")


def test_list_and_by_category():
    registry = ProviderRegistry()
    registry.register(_provider("acme", category="hosting"))
    registry.register(_provider("beta", category="payment_processor"))
    assert len(registry.list()) == 2
    assert [p.provider_id for p in registry.by_category("hosting")] == ["acme"]
    assert registry.by_category("crm") == ()
