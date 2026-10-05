"""Cross-surface regression tests for secret-prefix boundary checks."""
from collections.abc import Callable

import pytest

from evaluation.companyos import service_delivery
from evaluation.trustos import security_scanner_adapter
from scripts import (
    run_client_service_intake,
    run_companyos_approval_ledger,
    run_companyos_provider_registry,
    run_serpapi_commerce_projection,
    run_trustos_control_plane,
)
from services.consulting_engagement import schemas as engagement_schemas
from services.consulting_offers import schemas as offer_schemas
from services.market_research import report as market_research_report


Guard = Callable[[str], object]


def _rejects(guard: Guard, value: str) -> bool:
    try:
        result = guard(value)
    except ValueError:
        return True
    if isinstance(result, bool):
        return result
    if isinstance(result, str):
        return result != value
    return False


BOUNDARY_GUARDS: tuple[tuple[str, Guard], ...] = (
    (
        "companyos_service_delivery",
        lambda value: service_delivery._reject_secret_shaped(value, field_name="candidate_id"),
    ),
    ("companyos_service_delivery_redactor", service_delivery._redact_client_unsafe_values),
    ("trustos_security_scanner", lambda value: security_scanner_adapter._secret_like({"summary": value})),
    ("consulting_engagement_schema", lambda value: engagement_schemas._safe_text(value, "candidate_id")),
    ("consulting_offer_schema", lambda value: offer_schemas._safe_text(value, "candidate_id")),
    ("market_research_input", lambda value: market_research_report._validate_safe_inputs({"candidate_id": value})),
    ("trustos_cli", lambda value: run_trustos_control_plane._secret_like({"note": value})),
    ("provider_registry_cli", lambda value: run_companyos_provider_registry._secret_like({"note": value})),
    ("serpapi_projection_cli", lambda value: run_serpapi_commerce_projection._secret_like({"note": value})),
    ("approval_ledger_cli", lambda value: run_companyos_approval_ledger._secret_like({"note": value})),
    (
        "client_service_intake_cli",
        lambda value: run_client_service_intake._reject_secret_shaped_recursive(value, field_name="candidate_id"),
    ),
)

AIZA_GUARDS: tuple[tuple[str, Guard], ...] = (
    ("trustos_security_scanner", lambda value: security_scanner_adapter._secret_like({"summary": value})),
    ("trustos_cli", lambda value: run_trustos_control_plane._secret_like({"note": value})),
    ("provider_registry_cli", lambda value: run_companyos_provider_registry._secret_like({"note": value})),
    ("serpapi_projection_cli", lambda value: run_serpapi_commerce_projection._secret_like({"note": value})),
)

SECRET_SHAPES = (
    "sk-" + "SYNTHETICEXAMPLE0000",
    "api%3Dsk-" + "SYNTHETICEXAMPLE0000",
    r"line\nsk-" + "SYNTHETICEXAMPLE0000",
)


@pytest.mark.parametrize("candidate_id", ("desk-clamp-lamp", "desk-clamp-lamp-amazon-mirror"))
@pytest.mark.parametrize(("guard_name", "guard"), BOUNDARY_GUARDS, ids=[name for name, _ in BOUNDARY_GUARDS])
def test_hyphenated_candidate_ids_are_not_secret_markers(guard_name: str, guard: Guard, candidate_id: str):
    assert not _rejects(guard, candidate_id), guard_name


@pytest.mark.parametrize("secret_shape", SECRET_SHAPES, ids=("prefix", "url-encoded-separator", "escaped-newline"))
@pytest.mark.parametrize(("guard_name", "guard"), BOUNDARY_GUARDS, ids=[name for name, _ in BOUNDARY_GUARDS])
def test_secret_shaped_values_still_fail_closed(guard_name: str, guard: Guard, secret_shape: str):
    assert _rejects(guard, secret_shape), guard_name


@pytest.mark.parametrize(("guard_name", "guard"), AIZA_GUARDS, ids=[name for name, _ in AIZA_GUARDS])
def test_case_insensitive_google_secret_marker_still_fails_closed(guard_name: str, guard: Guard):
    assert _rejects(guard, "AIza" + "SYNTHETICEXAMPLE0000"), guard_name
