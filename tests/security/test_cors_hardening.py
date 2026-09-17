"""Tests for CORS hardening, wildcard rejection, and environment separation."""
from __future__ import annotations

import pytest

from backend.security.cors import (
    DEFAULT_LOCAL_ORIGINS,
    get_effective_allowed_origins,
    parse_allowed_origins,
    validate_allowed_origins,
    validate_cors_for_startup,
)


def test_parse_allowed_origins():
    raw = " https://app.marketos.com/ , http://localhost:3000/ "
    parsed = parse_allowed_origins(raw)
    assert parsed == ["https://app.marketos.com", "http://localhost:3000"]


def test_production_wildcard_rejection():
    # In production mode with wildcard
    env = {"MARKETOS_ENVIRONMENT": "production", "ALLOWED_ORIGINS": "*"}
    report = validate_allowed_origins(["*"], mvp_mode=True)
    assert report["mvp_safe"] is False
    assert "wildcard_origin_not_allowed_in_mvp_mode" in report["blockers"]

    # Startup validation must fail closed
    with pytest.raises(RuntimeError) as exc:
        validate_cors_for_startup(env)
    assert "Production CORS configuration rejected" in str(exc.value)


def test_production_missing_origins_rejection():
    env = {"MARKETOS_ENVIRONMENT": "production"}
    report = validate_allowed_origins([], mvp_mode=True)
    assert report["mvp_safe"] is False
    assert "allowed_origins_required_in_mvp_mode" in report["blockers"]

    with pytest.raises(RuntimeError) as exc:
        validate_cors_for_startup(env)
    assert "Production CORS configuration rejected" in str(exc.value)


def test_production_explicit_valid_origins_pass():
    env = {
        "MARKETOS_ENVIRONMENT": "production",
        "ALLOWED_ORIGINS": "https://app.marketos.com, https://admin.marketos.com",
    }
    effective = validate_cors_for_startup(env)
    assert effective == ["https://app.marketos.com", "https://admin.marketos.com"]


def test_local_development_defaults():
    env = {"MARKETOS_ENVIRONMENT": "development"}
    effective = get_effective_allowed_origins(env)
    assert effective == DEFAULT_LOCAL_ORIGINS
    assert "http://localhost:3000" in effective
    assert "http://localhost:5173" in effective
