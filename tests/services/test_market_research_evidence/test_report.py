import json
from pathlib import Path

import pytest

from services.market_research_evidence import (
    MISSING,
    build_evidence_integrity_report,
    build_observation_identity,
    build_source_identity,
    classify_freshness,
    detect_field_conflicts,
    render_evidence_integrity_markdown,
    validate_binding,
)
from services.market_research_evidence.identity import InvalidBindingError
from services.market_research_evidence.schemas import EvidenceProvenance, FieldObservation, ObservationIdentity, SourceIdentity

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "market_research_evidence"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


_MARKETPLACE = {
    "evidence_mode": "sanitized_report",
    "candidates": [
        {
            "candidate_id": "cand-1",
            "query": "portable blender",
            "observed_at": "2026-08-01",
            "score": {"overall_marketplace_opportunity": 0.7, "saturation_score": 0.4},
        }
    ],
}
_SUPPLIER = {
    "evidence_mode": "sanitized_report",
    "candidates": [
        {
            "candidate_id": "cand-1",
            "query": "portable blender",
            "offers": [{"supplier": "supplier-a", "shipping_cost": 4.5}],
            "score": {"overall_supplier_feasibility": 0.6},
        }
    ],
}
_SUPPLIER_NO_SHIPPING = {
    "evidence_mode": "sanitized_report",
    "candidates": [
        {
            "candidate_id": "cand-1",
            "query": "portable blender",
            "offers": [{"supplier": "supplier-a"}],
            "score": {"overall_supplier_feasibility": 0.6},
        }
    ],
}
_PUBLIC_MARKET = {
    "evidence_mode": "sanitized_report",
    "candidate_results": [
        {
            "candidate_id": "cand-1",
            "evidence": [{"source_domain": "example.com", "price": 29.99, "shipping_cost": 6.0}],
        }
    ],
}


def _build(**overrides):
    kwargs = dict(candidate_id="cand-1", workspace_id="ws-1", as_of="2026-09-22")
    kwargs.update(overrides)
    return build_evidence_integrity_report(**kwargs)


# --- typed provenance ---------------------------------------------------


def test_provenance_records_carry_source_and_observation_identity():
    result = _build(marketplace_report=_MARKETPLACE)
    assert result.provenance_records
    for record in result.provenance_records:
        assert isinstance(record, EvidenceProvenance)
        assert isinstance(record.source, SourceIdentity)
        assert isinstance(record.observation, ObservationIdentity)
        assert record.source.fingerprint
        assert record.observation.fingerprint


def test_field_observation_carries_its_own_provenance():
    result = _build(marketplace_report=_MARKETPLACE)
    for item in result.field_observations:
        assert isinstance(item, FieldObservation)
        assert item.provenance.pillar


# --- candidate/workspace binding -----------------------------------------


def test_valid_binding_is_accepted():
    validate_binding("cand-1", "ws-1")


@pytest.mark.parametrize("candidate_id,workspace_id", [("", "ws-1"), ("cand-1", ""), ("../etc", "ws-1"), ("cand-1", "ws;drop"), ("cand 1", "ws-1")])
def test_invalid_binding_is_rejected(candidate_id, workspace_id):
    with pytest.raises(InvalidBindingError):
        validate_binding(candidate_id, workspace_id)


def test_build_report_rejects_invalid_binding():
    with pytest.raises(InvalidBindingError):
        build_evidence_integrity_report(candidate_id="bad id", workspace_id="ws-1")


def test_observation_identity_binds_candidate_and_workspace():
    a = build_observation_identity("cand-1", "ws-1", "price")
    b = build_observation_identity("cand-1", "ws-2", "price")
    assert a.fingerprint != b.fingerprint


def test_source_identity_is_deterministic_for_identical_inputs():
    a = build_source_identity("supplier", "supplier-a")
    b = build_source_identity("supplier", "supplier-a")
    assert a.fingerprint == b.fingerprint
    c = build_source_identity("supplier", "supplier-b")
    assert a.fingerprint != c.fingerprint


# --- freshness classification --------------------------------------------


def test_freshness_supplied_within_window():
    assert classify_freshness("2026-08-01", "2026-09-22") == "supplied"


def test_freshness_stale_beyond_window():
    assert classify_freshness("2024-01-01", "2026-09-22") == "stale"


def test_freshness_future_dated():
    assert classify_freshness("2027-01-01", "2026-09-22") == "future"


def test_freshness_unknown_when_unparsable():
    assert classify_freshness("not-a-real-date", "2026-09-22") == "unknown"


def test_freshness_missing_when_absent():
    assert classify_freshness(None, "2026-09-22") == "missing"
    assert classify_freshness("", "2026-09-22") == "missing"


def test_stale_flagged_via_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = _build(candidate_id="cand-stale", as_of=fixture["as_of"], marketplace_report=fixture["stale_marketplace_report"])
    freshness = {record.observation.field: record.freshness_status for record in result.provenance_records}
    assert any(status == "stale" for status in freshness.values())


def test_future_flagged_via_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = _build(candidate_id="cand-future", as_of=fixture["as_of"], marketplace_report=fixture["future_marketplace_report"])
    freshness = {record.observation.field: record.freshness_status for record in result.provenance_records}
    assert any(status == "future" for status in freshness.values())


def test_unknown_freshness_flagged_via_fixture():
    fixture = _load_fixture("stale_and_future.json")
    result = _build(candidate_id="cand-unknown", as_of=fixture["as_of"], marketplace_report=fixture["unknown_marketplace_report"])
    assert result.unknown_freshness_fields


def test_offer_and_public_observation_dates_reach_provenance():
    supplier = {
        "evidence_mode": "sanitized_report",
        "candidates": [{
            "candidate_id": "cand-1",
            "offers": [{"supplier": "supplier-a", "shipping_cost": 4.5, "observed_at": "2024-01-01"}],
            "score": {"overall_supplier_feasibility": 0.6},
        }],
    }
    public_market = {
        "evidence_mode": "sanitized_report",
        "candidate_results": [{
            "candidate_id": "cand-1",
            "evidence": [{"source_domain": "example.com", "price": 10, "observed_at": "2024-01-01"}],
        }],
    }

    result = _build(supplier_report=supplier, public_market_benchmark_report=public_market)

    observed = {(item.field, item.provenance.observed_at, item.provenance.freshness_status) for item in result.field_observations}
    assert ("shipping_cost", "2024-01-01", "stale") in observed
    assert ("price", "2024-01-01", "stale") in observed


# --- deterministic conflict detection -------------------------------------


def test_detect_field_conflicts_is_empty_for_agreeing_sources():
    obs = (
        FieldObservation("price", 10.0, _fake_provenance("public_market_benchmark", "a")),
        FieldObservation("price", 10.0, _fake_provenance("public_market_benchmark", "b")),
    )
    assert detect_field_conflicts("cand-1", obs) == ()


def test_detect_field_conflicts_flags_disagreement():
    obs = (
        FieldObservation("price", 10.0, _fake_provenance("public_market_benchmark", "a")),
        FieldObservation("price", 25.0, _fake_provenance("public_market_benchmark", "b")),
    )
    findings = detect_field_conflicts("cand-1", obs)
    assert len(findings) == 1
    assert findings[0].field == "price"
    assert findings[0].delta == 15.0


def test_detect_field_conflicts_ignores_missing_and_unknown_sentinels():
    obs = (
        FieldObservation("price", MISSING, _fake_provenance("public_market_benchmark", "a")),
        FieldObservation("price", 25.0, _fake_provenance("public_market_benchmark", "b")),
    )
    assert detect_field_conflicts("cand-1", obs) == ()


def test_conflict_is_deterministic_across_repeated_calls():
    obs = (
        FieldObservation("shipping_cost", 4.5, _fake_provenance("supplier", "supplier-a")),
        FieldObservation("shipping_cost", 6.0, _fake_provenance("public_market_benchmark", "example.com")),
    )
    first = detect_field_conflicts("cand-1", obs)
    second = detect_field_conflicts("cand-1", obs)
    assert first == second


def test_cross_source_logistics_conflict_via_fixture():
    fixture = _load_fixture("logistics_conflict.json")
    result = _build(
        marketplace_report=fixture["marketplace_report"],
        supplier_report=fixture["supplier_report"],
        public_market_benchmark_report=fixture["public_market_benchmark_report"],
    )
    assert result.deterministic_conflict_detected is True
    fields = {item.field for item in result.deterministic_conflicts}
    assert "shipping_cost" in fields
    assert "price" in fields


def test_this_conflict_is_not_the_alias_collapse_mechanism():
    """The known concern: source_conflicts must not merely be a pass-through
    of opportunity_synthesis's alias_notes. This fixture has no aliased
    candidate rows at all (a single candidate_id per pillar, no
    source_family tags), so alias_notes is empty, yet the deterministic,
    field-level detector still finds the real cross-source disagreement."""
    fixture = _load_fixture("logistics_conflict.json")
    result = _build(
        marketplace_report=fixture["marketplace_report"],
        supplier_report=fixture["supplier_report"],
        public_market_benchmark_report=fixture["public_market_benchmark_report"],
    )
    assert result.alias_collapse_notes == ()
    assert result.deterministic_conflicts != ()


# --- missing-vs-zero preservation ------------------------------------------


def test_missing_shipping_cost_is_never_reported_as_zero():
    result = _build(supplier_report=_SUPPLIER_NO_SHIPPING)
    assert "supplier.shipping_cost" in result.missing_fields
    for item in result.field_observations:
        if item.field == "shipping_cost":
            assert item.value != 0


def test_supplied_shipping_cost_is_the_real_number():
    result = _build(supplier_report=_SUPPLIER)
    shipping = [item.value for item in result.field_observations if item.field == "shipping_cost"]
    assert shipping == [4.5]


def test_all_pillars_missing_reports_missing_not_zero_or_guessed():
    result = _build()
    assert result.field_observations == ()
    assert "marketplace.overall_marketplace_opportunity" in result.missing_fields
    assert "supplier.shipping_cost" in result.missing_fields
    assert "public_market_benchmark.price" in result.missing_fields


# --- explicit unknown/unavailable states -----------------------------------


def test_candidate_not_matched_is_recorded_explicitly():
    other = {"evidence_mode": "sanitized_report", "candidates": [{"candidate_id": "some-other-candidate", "query": "x", "score": {"overall_marketplace_opportunity": 0.5, "saturation_score": 0.2}}]}
    result = _build(marketplace_report=other)
    assert "marketplace.candidate_not_matched" in result.missing_fields


# --- negative controls: evidence cannot become proof/clearance/approval ----


def test_negative_controls_are_always_true():
    result = _build(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, public_market_benchmark_report=_PUBLIC_MARKET)
    controls = result.negative_controls.to_dict()
    assert all(controls.values())


FORBIDDEN_PHRASES = (
    "is supplier proof",
    "counts as supplier proof",
    "legal clearance granted",
    "constitutes legal clearance",
    "approved for promotion",
    "authorized to launch",
    "launch authorized",
    "launch approved",
    "is compliant",
    "is certified",
)


def test_negative_control_language_never_appears_as_an_affirmative_claim():
    result = _build(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, public_market_benchmark_report=_PUBLIC_MARKET)
    data = json.dumps(result.to_dict())
    markdown = render_evidence_integrity_markdown(result)
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in data.lower()
        assert phrase not in markdown.lower()


def test_limitations_state_all_four_negative_controls():
    result = _build()
    joined = " ".join(result.limitations)
    assert "not_supplier_proof" in joined
    assert "not_legal_clearance" in joined
    assert "not_promotion_approval" in joined
    assert "launch_approval" in joined


# --- TrustOS boundary / redaction / fingerprints ---------------------------


def test_client_export_safe_and_no_leakage_for_a_normal_report():
    result = _build(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, public_market_benchmark_report=_PUBLIC_MARKET)
    assert result.client_export_safe is True
    assert result.leakage_findings == ()


def test_fingerprint_is_stable_for_identical_input():
    a = _build(marketplace_report=_MARKETPLACE)
    b = _build(marketplace_report=_MARKETPLACE)
    assert a.fingerprint == b.fingerprint


def test_fingerprint_changes_when_evidence_changes():
    a = _build(marketplace_report=_MARKETPLACE)
    b = _build(marketplace_report=_SUPPLIER)
    assert a.fingerprint != b.fingerprint


def test_fingerprint_is_independent_of_generated_at():
    a = _build(marketplace_report=_MARKETPLACE)
    import time

    time.sleep(0.01)
    b = _build(marketplace_report=_MARKETPLACE)
    assert a.generated_at != b.generated_at
    assert a.fingerprint == b.fingerprint


# --- JSON / Markdown output -------------------------------------------------


def test_json_report_is_json_safe_and_complete():
    result = _build(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, public_market_benchmark_report=_PUBLIC_MARKET)
    data = result.to_dict()
    json.dumps(data)  # must not raise
    for key in ("provenance_records", "field_observations", "missing_fields", "deterministic_conflicts", "alias_collapse_notes", "negative_controls", "leakage_findings", "fingerprint"):
        assert key in data


def test_markdown_report_contains_every_required_section():
    result = _build(marketplace_report=_MARKETPLACE, supplier_report=_SUPPLIER, public_market_benchmark_report=_PUBLIC_MARKET)
    markdown = render_evidence_integrity_markdown(result)
    for heading in (
        "Candidate & Workspace Binding",
        "Evidence Provenance",
        "Field Observations",
        "Missing Fields",
        "Deterministic Conflicts",
        "Existing Alias-Collapse Notes",
        "TrustOS Client-Safety Boundary",
        "Negative Controls",
        "Limitations",
        "Report Fingerprint",
        "Disclaimer",
    ):
        assert heading in markdown


def test_report_is_read_only_and_never_claims_network_calls():
    result = _build(marketplace_report=_MARKETPLACE)
    assert result.read_only is True
    assert result.network_calls is False
    assert result.mutated is False


def _fake_provenance(pillar: str, source_ref: str) -> EvidenceProvenance:
    return EvidenceProvenance(
        pillar=pillar,
        source=build_source_identity(pillar, source_ref),
        observation=build_observation_identity("cand-1", "ws-1", "price"),
        evidence_mode="sanitized_report",
        observed_at=MISSING,
        freshness_status="supplied",
        capture_method="offline_report",
    )
