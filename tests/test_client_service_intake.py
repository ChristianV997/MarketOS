"""Tests for scripts/run_client_service_intake.py.

This bridge composes evaluation.companyos.service_delivery's existing
canonical intake/data-quality/economics/deliverable authorities rather
than re-implementing any of them, so these tests drive the real chain
with synthetic, deliberately non-PII fixture data (no real client names,
emails, account identifiers, or ad-export-shaped payloads anywhere in
this file, per this lane's explicit fixture-safety requirement).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.deliverables.registry import DeliverableRegistry
from backend.workspaces.client_workspace import ClientWorkspace
from backend.workspaces.registry import WorkspaceRegistry
from scripts import run_client_service_intake as bridge


def _consent(scope: str = "synthetic diagnostic scope"):
    return {"granted": True, "scope": scope, "granted_by": "synthetic-test-contact", "granted_at": "2026-09-19"}


def _adequate_fields():
    return {name: {"available": True, "as_of_days_ago": 5} for name in bridge.REQUIRED_CLIENT_DATA_FIELDS}


def _base_intake(**overrides):
    raw = {
        "schema": bridge.SCHEMA,
        "consent": _consent(),
        "client_id": "client-synthetic-001",
        "workspace_name": "Synthetic Test Workspace",
        "package_id": "unit-economics-cac-roas-diagnostic",
        "scope": "synthetic Q3 diagnostic",
        "data_fields": _adequate_fields(),
        "economics_inputs": {
            "fee": {"amount": "1500", "currency": "USD", "tax_inclusion_state": "exclusive"},
            "ad_spend": {"amount": "10000", "currency": "USD"},
            "roas_before": "1.8",
            "roas_after": "2.3",
            "cac_before": {"amount": "25", "currency": "USD"},
            "cac_after": {"amount": "18", "currency": "USD"},
            "delivery_hours": "24",
            "capacity_hours": "160",
        },
        "evidence": [{"evidence_id": "ev-synthetic-1", "source_type": "client_provided_export", "evidence_state": "observed", "captured_at": "2026-09-01"}],
    }
    raw.update(overrides)
    return raw


def _registries(tmp_path: Path):
    return (
        WorkspaceRegistry(str(tmp_path / "workspaces.json")),
        DeliverableRegistry(str(tmp_path / "deliverables.json")),
    )


# ---------------------------------------------------------------------------
# Full chain, real execution
# ---------------------------------------------------------------------------


def test_adequate_data_reaches_eligible_with_real_computed_economics(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    report = bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "eligible"
    assert report["lifecycle_state"] == "eligible"
    assert report["economics_error"] is None
    assert report["data_quality"]["status"] == "adequate"
    assert report["deliverable"]["status"] == "completed"
    derived = report["deliverable"]["sections"][0]["metadata"]["derived_values"]
    # 1180.00 = fee(1500) - delivery_cost(280 labor+contractor from package
    # defaults) - tooling(20) - pass_through(0) - reserve(20), matching the
    # canonical kernel's own contribution formula, not re-derived here.
    assert derived["contribution"]["amount"] == "1180.0"
    assert derived["contribution"]["currency"] == "USD"


def test_report_truthfully_discloses_local_registry_mutation(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    report = bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)

    assert report["read_only"] is False
    assert report["mutated"] is True
    assert report["mutation_scope"] == "local_workspace_and_deliverable_registries"
    assert report["external_actions"] is False
    assert "Do not delete shared registry files" in report["rollback"]


def test_run_requires_explicit_registries_to_avoid_shared_state_writes():
    with pytest.raises(bridge.IntakeError, match="explicit workspace and deliverable registries"):
        bridge.run(_base_intake())


def test_missing_fields_reach_data_inadequate_never_eligible(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(data_fields={"orders": {"available": True}}, client_id="client-synthetic-002", workspace_name="Synthetic Test Workspace Two")
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "data_inadequate"
    assert report["lifecycle_state"] == "data_inadequate"
    assert report["data_quality"]["data_inadequate"] is True
    assert report["deliverable"]["status"] == "blocked"
    assert report["deliverable"]["sections"][0]["metadata"]["derived_values"] == {}
    assert "client_identity" in report["data_quality"]["missing_fields"]


def test_currency_mismatch_is_a_reported_blocker_never_a_crash(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(
        client_id="client-synthetic-003", workspace_name="Synthetic Test Workspace Three",
        economics_inputs={
            "fee": {"amount": "20000", "currency": "MXN"},
            "ad_spend": {"amount": "10000", "currency": "USD"},
            "roas_before": "1", "roas_after": "2",
            "cac_before": {"amount": "40", "currency": "USD"}, "cac_after": {"amount": "25", "currency": "USD"},
        },
    )
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "blocked"
    assert "currency mismatch" in report["economics_error"]
    assert report["deliverable"]["status"] == "blocked"


def test_non_numeric_economics_field_is_a_reported_blocker_never_a_crash(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(client_id="client-synthetic-004", workspace_name="Synthetic Test Workspace Four")
    intake["economics_inputs"]["fee"]["amount"] = "not-a-number"
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "blocked"
    assert "not a valid number" in report["economics_error"]


def test_a_non_finite_roas_is_a_reported_blocker_never_an_uncaught_crash(tmp_path: Path):
    """Regression: EconomicsError (raised deep inside
    evaluate_engagement_economics/calculate_service_economics for a
    non-finite ROAS) was previously uncaught by _try_build_economics,
    crashing run() with a traceback instead of reporting a blocker --
    confirmed via direct reproduction before this fix."""
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(client_id="client-synthetic-006a", workspace_name="Synthetic Test Workspace Six A")
    intake["economics_inputs"]["roas_before"] = "nan"
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)  # must not raise
    assert report["classification"] == "blocked"
    assert report["economics_error"]


def test_a_negative_labor_cost_is_a_reported_blocker_never_an_uncaught_crash(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(client_id="client-synthetic-006b", workspace_name="Synthetic Test Workspace Six B")
    intake["economics_inputs"]["labor_cost"] = {"amount": "-500", "currency": "USD"}
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)  # must not raise
    assert report["classification"] == "blocked"
    assert report["economics_error"]


def test_an_unrecognized_evidence_state_is_a_reported_blocker_never_an_uncaught_crash(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(client_id="client-synthetic-006c", workspace_name="Synthetic Test Workspace Six C")
    intake["evidence"][0]["evidence_state"] = "totally-made-up-state"
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)  # must not raise
    assert report["classification"] == "blocked"
    assert report["economics_error"]


def test_a_blocked_economics_outcome_never_leaves_lifecycle_state_as_eligible(tmp_path: Path):
    """Regression: previously classification=="blocked" (economics failed)
    could coexist with lifecycle_state=="eligible", which a downstream
    consumer keying off lifecycle_state alone could misread as cleared to
    advance. The engagement must move to "paused" instead."""
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(
        client_id="client-synthetic-007", workspace_name="Synthetic Test Workspace Seven",
        economics_inputs={
            "fee": {"amount": "20000", "currency": "MXN"},
            "ad_spend": {"amount": "10000", "currency": "USD"},
            "roas_before": "1", "roas_after": "2",
            "cac_before": {"amount": "40", "currency": "USD"}, "cac_after": {"amount": "25", "currency": "USD"},
        },
    )
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "blocked"
    assert report["lifecycle_state"] != "eligible"
    assert report["lifecycle_state"] == "paused"


# ---------------------------------------------------------------------------
# Consent gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "consent",
    [
        None,
        {},
        {"granted": False, "scope": "x"},
        {"granted": True, "scope": ""},
        {"granted": True, "scope": "   "},
        {"granted": "yes", "scope": "x"},  # truthy string is not True
    ],
)
def test_missing_or_incomplete_consent_is_refused(tmp_path: Path, consent):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(consent=consent) if consent is not None else {k: v for k, v in _base_intake().items() if k != "consent"}
    with pytest.raises(bridge.IntakeError, match="consent"):
        bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)


def test_valid_consent_is_accepted_and_echoed_back(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    report = bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["consent_scope"] == "synthetic diagnostic scope"


# ---------------------------------------------------------------------------
# Secret-shape rejection, anywhere in the file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw["data_fields"]["orders"].__setitem__("note", "sk-live-abcdefghijklmnopqrstuvwx"),
        lambda raw: raw["consent"].__setitem__("scope", "bearer abcdefghijklmnop"),
        lambda raw: raw["evidence"][0].__setitem__("document_ref", "ghp_abcdefghijklmnopqrstuvwx"),
        lambda raw: raw.__setitem__("scope", "-----BEGIN PRIVATE KEY-----"),
    ],
)
def test_secret_shaped_values_anywhere_in_the_file_are_rejected(tmp_path: Path, mutate):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake()
    mutate(intake)
    with pytest.raises(bridge.IntakeError, match="secret-shaped"):
        bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)


# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------


def test_unknown_package_id_is_rejected(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    with pytest.raises(bridge.IntakeError, match="unknown package_id"):
        bridge.run(_base_intake(package_id="not-a-real-package"), workspace_registry=ws_registry, deliverable_registry=dl_registry)


@pytest.mark.parametrize("field", ["client_id", "package_id", "scope"])
def test_missing_required_top_level_field_is_rejected(tmp_path: Path, field):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(**{field: ""})
    with pytest.raises(bridge.IntakeError):
        bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)


def test_missing_data_fields_and_no_csv_override_is_rejected(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = {k: v for k, v in _base_intake().items() if k != "data_fields"}
    with pytest.raises(bridge.IntakeError, match="data_fields"):
        bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)


# ---------------------------------------------------------------------------
# CSV data-quality table
# ---------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    import csv

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["field", "available", "as_of_days_ago", "conflicting"])
        writer.writeheader()
        writer.writerows(rows)


def test_csv_data_quality_table_supplies_the_assessment_when_json_omits_it(tmp_path: Path):
    csv_path = tmp_path / "dq.csv"
    _write_csv(csv_path, [{"field": name, "available": "true", "as_of_days_ago": "5", "conflicting": "false"} for name in bridge.REQUIRED_CLIENT_DATA_FIELDS])
    override = bridge.load_data_quality_csv(csv_path)
    assert set(override) == set(bridge.REQUIRED_CLIENT_DATA_FIELDS)
    ws_registry, dl_registry = _registries(tmp_path)
    intake = {k: v for k, v in _base_intake().items() if k != "data_fields"}
    report = bridge.run(intake, data_quality_override=override, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "eligible"


def test_csv_takes_precedence_over_a_conflicting_json_data_fields_block(tmp_path: Path):
    csv_path = tmp_path / "dq_inadequate.csv"
    _write_csv(csv_path, [{"field": "orders", "available": "true", "as_of_days_ago": "5", "conflicting": "false"}])
    override = bridge.load_data_quality_csv(csv_path)
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake()  # json data_fields here is fully adequate
    report = bridge.run(intake, data_quality_override=override, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["classification"] == "data_inadequate"  # the sparse CSV override won, not the adequate JSON


def test_csv_with_an_unknown_field_name_is_rejected(tmp_path: Path):
    csv_path = tmp_path / "dq_bad.csv"
    _write_csv(csv_path, [{"field": "not_a_real_field", "available": "true", "as_of_days_ago": "", "conflicting": ""}])
    with pytest.raises(bridge.IntakeError, match="unknown data-quality field"):
        bridge.load_data_quality_csv(csv_path)


def test_csv_with_non_numeric_age_is_rejected(tmp_path: Path):
    csv_path = tmp_path / "dq_bad_age.csv"
    _write_csv(csv_path, [{"field": "orders", "available": "true", "as_of_days_ago": "not-a-number", "conflicting": ""}])
    with pytest.raises(bridge.IntakeError, match="non-numeric as_of_days_ago"):
        bridge.load_data_quality_csv(csv_path)


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "Infinity"])
def test_csv_with_a_non_finite_age_is_rejected_not_silently_treated_as_fresh(tmp_path: Path, value):
    """Regression: bare float() accepts "nan"/"inf" without raising, and
    assess_client_data_quality's staleness check (`age > max_age_days`) is
    silently False for NaN (verified directly: float("nan") > 90.0 is
    False) -- an unparseable-looking age was previously stored as-is and
    treated as fresh, adequate data instead of being rejected."""
    csv_path = tmp_path / "dq_non_finite_age.csv"
    _write_csv(csv_path, [{"field": "orders", "available": "true", "as_of_days_ago": value, "conflicting": ""}])
    with pytest.raises(bridge.IntakeError, match="non-finite as_of_days_ago"):
        bridge.load_data_quality_csv(csv_path)


def test_csv_with_a_secret_shaped_value_is_rejected(tmp_path: Path):
    csv_path = tmp_path / "dq_secret.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        handle.write("field,available,as_of_days_ago,conflicting,note\n")
        handle.write("orders,true,5,false,sk-live-abcdefghijklmnopqrstuvwx\n")
    with pytest.raises(bridge.IntakeError, match="secret-shaped"):
        bridge.load_data_quality_csv(csv_path)


def test_csv_missing_required_columns_is_rejected(tmp_path: Path):
    csv_path = tmp_path / "dq_missing_cols.csv"
    csv_path.write_text("field_name,is_available\norders,true\n", encoding="utf-8")
    with pytest.raises(bridge.IntakeError, match="field.*available"):
        bridge.load_data_quality_csv(csv_path)


# ---------------------------------------------------------------------------
# Replay determinism
#
# The service layer this bridge composes has no idempotency/event-spine
# authority of its own (confirmed by reading evaluation/companyos/
# service_delivery.py and backend/deliverables/package.py), and this
# lane's own instructions are explicit: do not add one just to make a
# replay "look" perfectly identical. This test documents the real,
# verified boundary instead -- verified directly via two live CLI runs of
# byte-identical input files before writing this assertion.
# ---------------------------------------------------------------------------


def test_replaying_the_same_sanitized_input_is_deterministic_except_the_canonical_deliverable_timestamp(tmp_path: Path):
    """DeliverablePackage.created_at (backend/deliverables/package.py) is a
    pre-existing field on the canonical deliverable dataclass, defaulted
    via `field(default_factory=time.time)` -- a real wall-clock value this
    bridge neither sets nor has any parameter to override, and must not
    "fix" by constructing DeliverablePackage itself (that would duplicate
    the one existing deliverable-construction authority). Every other
    field -- engagement_id, workspace_id, deliverable package_id,
    lifecycle_state, data_quality, and every real number in
    derived_values -- is byte-identical across two independent runs of
    the same sanitized input."""
    registry_one, deliverables_one = _registries(tmp_path / "run1")
    registry_two, deliverables_two = _registries(tmp_path / "run2")
    intake = _base_intake()
    first = bridge.run(intake, workspace_registry=registry_one, deliverable_registry=deliverables_one)
    second = bridge.run(intake, workspace_registry=registry_two, deliverable_registry=deliverables_two)

    assert first["engagement_id"] == second["engagement_id"]
    assert first["workspace_id"] == second["workspace_id"]
    assert first["classification"] == second["classification"]
    assert first["lifecycle_state"] == second["lifecycle_state"]
    assert first["data_quality"] == second["data_quality"]

    # The one documented exception: a live wall-clock field on the
    # canonical DeliverablePackage this bridge does not control. Every
    # other deliverable key (package_id, status, sections/derived_values,
    # etc.) is asserted equal by this single loop -- checked both
    # directions so a key present on only one side is caught too.
    non_deterministic_fields = {"created_at"}
    assert set(first["deliverable"]) == set(second["deliverable"])
    for key in first["deliverable"]:
        if key in non_deterministic_fields:
            continue
        assert first["deliverable"][key] == second["deliverable"][key], key


# ---------------------------------------------------------------------------
# Workspace identity separation
# ---------------------------------------------------------------------------


def test_the_same_workspace_name_is_registered_once_and_reused(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    first = bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    second = bridge.run(_base_intake(client_id="client-synthetic-001-followup"), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert first["workspace_id"] == second["workspace_id"]
    assert len(ws_registry.list_all()) == 1


def test_a_non_client_service_workspace_with_the_same_name_is_rejected(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    ws_registry.register(ClientWorkspace(name="Synthetic Test Workspace", workspace_type="internal"))
    with pytest.raises(bridge.IntakeError, match="not client_service"):
        bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)


def test_the_registered_workspace_record_never_contains_business_data(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    raw_text = (tmp_path / "workspaces.json").read_text(encoding="utf-8")
    for leaked in ("10000", "1500", "roas", "cac_before", "revenue"):
        assert leaked not in raw_text, f"workspace registry unexpectedly contains {leaked!r}"


# ---------------------------------------------------------------------------
# Tax / currency provenance preserved verbatim
# ---------------------------------------------------------------------------


def test_top_level_evidence_field_actually_reaches_the_economics_computation(tmp_path: Path):
    """Regression: _try_build_economics originally read raw.get("evidence")
    where its own `raw` parameter was economics_inputs, a sibling object to
    the intake file's real top-level "evidence" field -- every
    caller-supplied evidence reference was silently dropped. Verified via
    ServiceEconomics.evidence_state, which only reflects a non-'unknown'
    value when at least one evidence_refs entry with a real evidence_state
    was actually threaded through."""
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(client_id="client-synthetic-008", workspace_name="Synthetic Test Workspace Eight")
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    assert report["deliverable"]["sections"][0]["metadata"]["confidence"] == "observed"


def test_tax_inclusion_state_is_preserved_verbatim_not_assumed(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    report = bridge.run(_base_intake(), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    contribution = report["deliverable"]["sections"][0]["metadata"]["derived_values"]["contribution"]
    assert contribution["tax_inclusion_state"] == "exclusive"  # from economics_inputs.fee, never defaulted


def test_tax_inclusion_state_defaults_to_unknown_when_not_supplied(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    intake = _base_intake(client_id="client-synthetic-005", workspace_name="Synthetic Test Workspace Five")
    del intake["economics_inputs"]["fee"]["tax_inclusion_state"]
    report = bridge.run(intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    contribution = report["deliverable"]["sections"][0]["metadata"]["derived_values"]["contribution"]
    assert contribution["tax_inclusion_state"] == "unknown"


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------


def test_missing_intake_file_is_rejected(tmp_path: Path):
    with pytest.raises(bridge.IntakeError, match="does not exist"):
        bridge.load_intake_file(tmp_path / "missing.json")


def test_html_intake_file_is_rejected(tmp_path: Path):
    path = tmp_path / "intake.json"
    path.write_text("<html><body>not json</body></html>", encoding="utf-8")
    with pytest.raises(bridge.IntakeError, match="HTML"):
        bridge.load_intake_file(path)


def test_malformed_json_intake_file_is_rejected(tmp_path: Path):
    path = tmp_path / "intake.json"
    path.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(bridge.IntakeError, match="malformed JSON"):
        bridge.load_intake_file(path)


def test_unsupported_schema_is_rejected(tmp_path: Path):
    path = tmp_path / "intake.json"
    path.write_text(json.dumps({"schema": "SomethingElse.v1"}), encoding="utf-8")
    with pytest.raises(bridge.IntakeError, match="unsupported intake schema"):
        bridge.load_intake_file(path)


def test_non_object_json_root_is_rejected(tmp_path: Path):
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(bridge.IntakeError, match="root must be an object"):
        bridge.load_intake_file(path)


# ---------------------------------------------------------------------------
# CLI exit codes, real file round trip
# ---------------------------------------------------------------------------


def test_cli_exit_code_zero_for_eligible(tmp_path: Path, capsys):
    intake_path = tmp_path / "intake.json"
    intake_path.write_text(json.dumps(_base_intake()), encoding="utf-8")
    exit_code = bridge.main([
        "--intake-json", str(intake_path),
        "--workspace-registry-path", str(tmp_path / "ws.json"),
        "--deliverable-registry-path", str(tmp_path / "dl.json"),
    ])
    assert exit_code == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["classification"] == "eligible"


def test_cli_default_registries_are_temporary_and_removed(tmp_path: Path, capsys, monkeypatch):
    intake_path = tmp_path / "intake.json"
    intake_path.write_text(json.dumps(_base_intake()), encoding="utf-8")
    workspace_paths: list[Path] = []
    deliverable_paths: list[Path] = []
    real_workspace_registry = bridge.WorkspaceRegistry
    real_deliverable_registry = bridge.DeliverableRegistry

    def workspace_registry(path):
        workspace_paths.append(Path(path))
        return real_workspace_registry(str(path))

    def deliverable_registry(path):
        deliverable_paths.append(Path(path))
        return real_deliverable_registry(str(path))

    monkeypatch.setattr(bridge, "WorkspaceRegistry", workspace_registry)
    monkeypatch.setattr(bridge, "DeliverableRegistry", deliverable_registry)

    assert bridge.main(["--intake-json", str(intake_path)]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["mutated"] is True
    assert len(workspace_paths) == len(deliverable_paths) == 1
    assert workspace_paths[0].parent == deliverable_paths[0].parent
    assert "marketos-client-service-intake-" in workspace_paths[0].parent.name
    assert not workspace_paths[0].exists()
    assert not deliverable_paths[0].exists()


def test_cli_exit_code_zero_for_data_inadequate(tmp_path: Path, capsys):
    intake_path = tmp_path / "intake.json"
    intake_path.write_text(json.dumps(_base_intake(data_fields={"orders": {"available": True}})), encoding="utf-8")
    exit_code = bridge.main([
        "--intake-json", str(intake_path),
        "--workspace-registry-path", str(tmp_path / "ws.json"),
        "--deliverable-registry-path", str(tmp_path / "dl.json"),
    ])
    assert exit_code == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["classification"] == "data_inadequate"


def test_cli_exit_code_one_for_blocked(tmp_path: Path, capsys):
    intake_path = tmp_path / "intake.json"
    bad = _base_intake()
    bad["economics_inputs"]["fee"]["currency"] = "MXN"
    intake_path.write_text(json.dumps(bad), encoding="utf-8")
    exit_code = bridge.main([
        "--intake-json", str(intake_path),
        "--workspace-registry-path", str(tmp_path / "ws.json"),
        "--deliverable-registry-path", str(tmp_path / "dl.json"),
    ])
    assert exit_code == 1
    captured = json.loads(capsys.readouterr().out)
    assert captured["classification"] == "blocked"


def test_cli_exit_code_two_for_malformed(tmp_path: Path, capsys):
    exit_code = bridge.main(["--intake-json", str(tmp_path / "does_not_exist.json")])
    assert exit_code == 2
    captured = json.loads(capsys.readouterr().out)
    assert captured["classification"] == "malformed"


def test_cli_with_csv_data_quality_flag_round_trips_through_real_files(tmp_path: Path, capsys):
    intake = {k: v for k, v in _base_intake().items() if k != "data_fields"}
    intake_path = tmp_path / "intake.json"
    intake_path.write_text(json.dumps(intake), encoding="utf-8")
    csv_path = tmp_path / "dq.csv"
    _write_csv(csv_path, [{"field": name, "available": "true", "as_of_days_ago": "5", "conflicting": "false"} for name in bridge.REQUIRED_CLIENT_DATA_FIELDS])
    exit_code = bridge.main([
        "--intake-json", str(intake_path),
        "--data-quality-csv", str(csv_path),
        "--workspace-registry-path", str(tmp_path / "ws.json"),
        "--deliverable-registry-path", str(tmp_path / "dl.json"),
    ])
    assert exit_code == 0
    captured = json.loads(capsys.readouterr().out)
    assert captured["classification"] == "eligible"


# ---------------------------------------------------------------------------
# Evidence pass-through
# ---------------------------------------------------------------------------


def test_evidence_refs_preserve_source_provenance_without_reimplementing_evidence_tracking():
    refs = bridge._evidence_refs_from([
        {"evidence_id": "ev-1", "source_type": "client_provided_export", "evidence_state": "observed", "captured_at": "2026-09-01", "human_confirmed": True},
    ])
    assert len(refs) == 1
    assert refs[0].evidence_id == "ev-1"
    assert refs[0].source_type == "client_provided_export"
    assert refs[0].evidence_state == "observed"
    assert refs[0].human_confirmed is True


def test_evidence_without_an_evidence_id_is_rejected():
    with pytest.raises(bridge.IntakeError, match="evidence_id"):
        bridge._evidence_refs_from([{"source_type": "client_provided_export"}])


# ---------------------------------------------------------------------------
# Classification vocabulary is closed and actually enforced
# ---------------------------------------------------------------------------


def test_every_real_outcome_classification_is_a_member_of_the_declared_closed_set(tmp_path: Path):
    ws_registry, dl_registry = _registries(tmp_path)
    eligible = bridge.run(_base_intake(client_id="c-a", workspace_name="W A"), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    inadequate = bridge.run(_base_intake(client_id="c-b", workspace_name="W B", data_fields={"orders": {"available": True}}), workspace_registry=ws_registry, deliverable_registry=dl_registry)
    blocked_intake = _base_intake(client_id="c-c", workspace_name="W C")
    blocked_intake["economics_inputs"]["fee"]["currency"] = "MXN"
    blocked = bridge.run(blocked_intake, workspace_registry=ws_registry, deliverable_registry=dl_registry)
    for report in (eligible, inadequate, blocked):
        assert report["classification"] in bridge.CLASSIFICATIONS
