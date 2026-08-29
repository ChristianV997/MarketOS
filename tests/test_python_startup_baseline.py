"""Regression checks for the supported Python import/startup boundary."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "backend.api",
        "backend.contracts.events",
        "backend.events.repository",
        "backend.adapters.alibaba_trends",
        "backend.adapters.tiktok_organic",
        "backend.observability.exporters",
        "evaluation",
        "orchestrator.main",
        "services.unit_economics",
    ],
)
def test_canonical_python_modules_import_without_credentials(module_name: str) -> None:
    module = importlib.import_module(module_name)

    assert module is not None
