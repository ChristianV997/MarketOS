"""Failure contracts for the portfolio API routes.

The route-level tests deliberately patch the existing domain authorities.  They
verify the boundary response without running providers, simulation jobs, or
live portfolio work.
"""

import json
import sys
import types

import pytest

from api.routes import portfolio as portfolio_routes


def test_portfolio_failure_is_unavailable_without_reflecting_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    portfolio_engine = types.ModuleType("backend.decision.portfolio_engine")

    def fail() -> dict[str, float]:
        raise RuntimeError("secret-path/canary-token")

    portfolio_engine.get_allocations = fail
    portfolio_engine.top_products = lambda *, n: []
    monkeypatch.setitem(sys.modules, "backend.decision.portfolio_engine", portfolio_engine)

    result = portfolio_routes.portfolio()

    assert "portfolio_allocation_unavailable" in caplog.text
    assert "RuntimeError" in caplog.text
    assert result == {
        "status": "unavailable",
        "error": "portfolio_unavailable",
        "allocations": {},
        "top_products": [],
    }
    assert "secret-path" not in json.dumps(result)
    assert "canary-token" not in json.dumps(result)


def test_portfolio_success_schema_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    portfolio_engine = types.ModuleType("backend.decision.portfolio_engine")

    portfolio_engine.get_allocations = lambda: {"sku-a": 1.0}
    portfolio_engine.top_products = lambda *, n: [{"product": "sku-a"}]
    monkeypatch.setitem(sys.modules, "backend.decision.portfolio_engine", portfolio_engine)

    assert portfolio_routes.portfolio() == {
        "allocations": {"sku-a": 1.0},
        "top_products": [{"product": "sku-a"}],
    }


def test_opportunities_failure_is_unavailable_and_bounded(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def fail(*_args, **_kwargs):
        raise RuntimeError("/private/server/path")

    simulation_engine = types.SimpleNamespace(score_signals=fail)
    monkeypatch.setitem(
        sys.modules,
        "simulation.engine",
        types.SimpleNamespace(simulation_engine=simulation_engine),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.content.patterns",
        types.SimpleNamespace(
            pattern_store=types.SimpleNamespace(get_patterns=lambda: {})
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.content.playbook",
        types.SimpleNamespace(
            playbook_memory=types.SimpleNamespace(all=lambda: [])
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "simulation.calibration",
        types.SimpleNamespace(
            calibration_store=types.SimpleNamespace(
                summary=lambda: {"by_product": {}}
            )
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "core.signals",
        types.SimpleNamespace(
            signal_engine=types.SimpleNamespace(get=lambda: [])
        ),
    )

    result = portfolio_routes.opportunities(limit=100)

    assert "opportunities_unavailable" in caplog.text
    assert "RuntimeError" in caplog.text
    assert result == {
        "status": "unavailable",
        "error": "opportunities_unavailable",
        "count": 0,
        "calibrated": False,
        "top_hooks": [],
        "top_angles": [],
        "opportunities": [],
    }
    assert len(json.dumps(result)) < 512
    assert "/private/server/path" not in json.dumps(result)
