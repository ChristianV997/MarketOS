"""Cross-surface regression tests for secret-prefix boundary checks."""
import json
from collections.abc import Callable

import pytest

from evaluation.companyos import service_delivery
from evaluation.commerce import commerce_operations_cycle, dataforseo_adapter, intelligence_adapter_plan
from evaluation.trustos import client_workspace_isolation, security_scanner_adapter
from scripts import (
    run_client_service_intake,
    run_companyos_approval_ledger,
    run_companyos_provider_registry,
    run_dataforseo_readonly_adapter,
    run_intelligence_adapter_plan,
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
    ("commerce_operations_cycle", lambda value: commerce_operations_cycle.reject_unsafe_input(value, label="candidate_id")),
    ("dataforseo_adapter", lambda value: dataforseo_adapter._secret_like({"note": value})),
    ("intelligence_adapter_plan", lambda value: intelligence_adapter_plan._secret_like({"note": value})),
    ("client_workspace_isolation", lambda value: bool(client_workspace_isolation.check_workspace_leakage({"note": value}))),
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
    ("dataforseo_cli", lambda value: run_dataforseo_readonly_adapter._secret_like({"note": value})),
    ("intelligence_adapter_cli", lambda value: run_intelligence_adapter_plan._secret_like({"note": value})),
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
    r"line\\nsk-" + "SYNTHETICEXAMPLE0000",
    "api%61sk-" + "SYNTHETICEXAMPLE0000",
)
ENCODED_SEPARATORS = (
    pytest.param(r"\b", id="escaped-backspace"),
    pytest.param(r"\B", id="escaped-uppercase-backspace"),
    pytest.param(r"\x20", id="escaped-hex-space"),
    pytest.param(r"\X20", id="escaped-uppercase-hex-space"),
    pytest.param("%253D", id="double-encoded-url-separator"),
    pytest.param(r"\u0020", id="escaped-unicode-space"),
    pytest.param(r"\U0020", id="escaped-uppercase-unicode-4hex"),
    pytest.param(r"\u00000020", id="escaped-lowercase-unicode-8hex"),
    pytest.param(r"\U00000020", id="escaped-uppercase-unicode-8hex"),
    pytest.param(r"\040", id="escaped-octal-space"),
    pytest.param(r"\00", id="escaped-octal-null"),
)
SYNTHETIC_SK = "sk-" + "SYNTHETICEXAMPLE0000"


@pytest.mark.parametrize(
    "candidate_id",
    (
        "desk-clamp-lamp",
        "desk-clamp-lamp-amazon-mirror",
        "whisk-attachment",
        "flask-holder",
        "disk-brake-pad",
        "risk-assessment-template",
        "kiosk-stand-mount",
        "brisk-morning-tea",
    ),
)
@pytest.mark.parametrize(("guard_name", "guard"), BOUNDARY_GUARDS, ids=[name for name, _ in BOUNDARY_GUARDS])
def test_hyphenated_candidate_ids_are_not_secret_markers(guard_name: str, guard: Guard, candidate_id: str):
    assert not _rejects(guard, candidate_id), guard_name


@pytest.mark.parametrize("secret_shape", SECRET_SHAPES, ids=("prefix", "url-encoded-separator", "escaped-newline", "legacy-percent-encoded-boundary"))
@pytest.mark.parametrize(("guard_name", "guard"), BOUNDARY_GUARDS, ids=[name for name, _ in BOUNDARY_GUARDS])
def test_secret_shaped_values_still_fail_closed(guard_name: str, guard: Guard, secret_shape: str):
    assert _rejects(guard, secret_shape), guard_name


@pytest.mark.parametrize("separator", ENCODED_SEPARATORS)
@pytest.mark.parametrize(("guard_name", "guard"), BOUNDARY_GUARDS, ids=[name for name, _ in BOUNDARY_GUARDS])
def test_escaped_secret_separators_fail_closed_across_guards(guard_name: str, guard: Guard, separator: str):
    assert _rejects(guard, separator + SYNTHETIC_SK), guard_name


@pytest.mark.parametrize("separator", ENCODED_SEPARATORS)
def test_commerce_cycle_rejection_does_not_echo_or_serialize_secret(separator: str):
    value = separator + SYNTHETIC_SK
    rejectors = (
        lambda: commerce_operations_cycle.reject_unsafe_input({"note": value}, label="fixture"),
        lambda: commerce_operations_cycle.build_commerce_operations_cycle(
            {"candidates": [{"candidate_id": "desk-clamp-lamp", "query": value}]}, None, None
        ),
    )
    for reject in rejectors:
        with pytest.raises(ValueError, match="secret-like or raw payload") as excinfo:
            reject()
        serialized_error = json.dumps({"error": str(excinfo.value)})
        assert value not in str(excinfo.value)
        assert SYNTHETIC_SK not in str(excinfo.value)
        assert value not in serialized_error
        assert SYNTHETIC_SK not in serialized_error


@pytest.mark.parametrize("separator", ENCODED_SEPARATORS)
def test_client_workspace_findings_do_not_serialize_secret(separator: str):
    value = separator + SYNTHETIC_SK
    findings = client_workspace_isolation.check_workspace_leakage({"note": value})
    serialized = json.dumps([finding.to_dict() for finding in findings])
    assert findings
    assert value not in serialized
    assert SYNTHETIC_SK not in serialized


@pytest.mark.parametrize(("guard_name", "guard"), AIZA_GUARDS, ids=[name for name, _ in AIZA_GUARDS])
def test_case_insensitive_google_secret_marker_still_fails_closed(guard_name: str, guard: Guard):
    assert _rejects(guard, "AIza" + "SYNTHETICEXAMPLE0000"), guard_name


OCTAL_AND_NESTED_SEPARATORS = (
    "\\1",
    "\\12",
    "\\012",
    "\\040",
    "\\011",
    "%" + "25" * 11 + "20",
    "%" + "25" * 30 + "20",
)


@pytest.mark.parametrize("separator", OCTAL_AND_NESTED_SEPARATORS)
def test_octal_and_deeply_nested_separators_fail_closed(separator: str):
    from evaluation.secret_markers import contains_boundary_prefixed_sk_token

    assert contains_boundary_prefixed_sk_token("a" + separator + SYNTHETIC_SK)
    # ordinary identifiers stay accepted
    for ordinary in ("desk-clamp-lamp", "brisk-walk", "task-list"):
        assert not contains_boundary_prefixed_sk_token(ordinary)


def test_ordinary_ids_not_flagged_by_nested_percent():
    from evaluation.secret_markers import contains_boundary_prefixed_sk_token

    assert not contains_boundary_prefixed_sk_token("desk-clamp-lamp%2520x")


def _leaky_key_payload(key: str) -> dict:
    return {"note": "ok", "nested": {key: "value"}}


@pytest.mark.parametrize("key", ["a%20" + SYNTHETIC_SK, SYNTHETIC_SK, "a\\012" + SYNTHETIC_SK])
def test_canary_mapping_keys_are_rejected_without_echo(key: str):
    payload = _leaky_key_payload(key)
    errors: list[BaseException] = []
    for call in (
        lambda: service_delivery._reject_secret_shaped_recursive(payload, field_name="intake_data"),
        lambda: run_client_service_intake._reject_secret_shaped_recursive(payload, field_name="intake"),
    ):
        with pytest.raises(ValueError) as excinfo:
            call()
        errors.append(excinfo.value)
    for error in errors:
        rendered = " ".join([str(error), repr(error), repr(error.args)])
        assert key not in rendered and SYNTHETIC_SK not in rendered
    findings = client_workspace_isolation.check_workspace_leakage(payload)
    serialized = json.dumps([finding.to_dict() for finding in findings])
    assert findings
    assert key not in serialized and SYNTHETIC_SK not in serialized


def test_redaction_removes_canary_keys_tuples_and_bytes():
    redacted = service_delivery._redact_client_unsafe_values(
        {SYNTHETIC_SK: "x", "items": (SYNTHETIC_SK, b"raw"), "ok": "desk-clamp-lamp"}
    )
    rendered = json.dumps(redacted, default=str)
    assert SYNTHETIC_SK not in rendered and "raw" not in rendered
    assert redacted["ok"] == "desk-clamp-lamp"


CONSUMER_KEY_PREDICATES: tuple[tuple[str, Callable[[dict], bool]], ...] = (
    ("commerce_operations_cycle", commerce_operations_cycle._secret_like),
    ("dataforseo_adapter", dataforseo_adapter._secret_like),
    ("intelligence_adapter_plan", intelligence_adapter_plan._secret_like),
    ("security_scanner_adapter", security_scanner_adapter._secret_like),
    ("trustos_cli", run_trustos_control_plane._secret_like),
    ("approval_ledger_cli", run_companyos_approval_ledger._secret_like),
    ("provider_registry_cli", run_companyos_provider_registry._secret_like),
    ("dataforseo_cli", run_dataforseo_readonly_adapter._secret_like),
    ("intelligence_adapter_cli", run_intelligence_adapter_plan._secret_like),
    ("serpapi_projection_cli", run_serpapi_commerce_projection._secret_like),
)


@pytest.mark.parametrize("key", ["a%20" + SYNTHETIC_SK, SYNTHETIC_SK, "a\\012" + SYNTHETIC_SK])
@pytest.mark.parametrize(("name", "predicate"), CONSUMER_KEY_PREDICATES)
def test_consumer_guards_reject_canary_mapping_keys(key: str, name: str, predicate: Callable[[dict], bool]):
    payload = _leaky_key_payload(key)
    assert predicate(payload), f"{name} failed to reject canary secret key"


@pytest.mark.parametrize("key", ["a%20" + SYNTHETIC_SK, SYNTHETIC_SK, "a\\012" + SYNTHETIC_SK])
def test_consumer_guards_reject_canary_mapping_keys_in_top_level_and_nested_without_echo(key: str):
    payload = _leaky_key_payload(key)
    with pytest.raises(ValueError) as excinfo:
        commerce_operations_cycle.reject_unsafe_input(payload, label="fixture")
    err = str(excinfo.value)
    assert key not in err and SYNTHETIC_SK not in err

    with pytest.raises(ValueError) as excinfo:
        market_research_report._validate_safe_inputs(payload)
    err = str(excinfo.value)
    assert key not in err and SYNTHETIC_SK not in err


@pytest.mark.parametrize("ordinary_key", ("desk-clamp-lamp", "desk-clamp-lamp-mirror", "kiosk-stand", "flask-holder"))
@pytest.mark.parametrize(("name", "predicate"), CONSUMER_KEY_PREDICATES)
def test_consumer_guards_accept_ordinary_mapping_keys(ordinary_key: str, name: str, predicate: Callable[[dict], bool]):
    payload = {"note": "ok", ordinary_key: "value", "nested": {ordinary_key: "another_value"}}
    assert not predicate(payload), f"{name} falsely rejected ordinary key {ordinary_key}"
    commerce_operations_cycle.reject_unsafe_input(payload, label="fixture")
    market_research_report._validate_safe_inputs(payload)
