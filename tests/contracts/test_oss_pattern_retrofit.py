"""tests/contracts/test_oss_pattern_retrofit.py — Unit and contract tests for OSS pattern retrofit.

Tests:
1. Run-level evidence lineage facets (OpenLineage + Dagster SDA emulation).
2. Explicit data-quality assertion states (Great Expectations emulation).
3. Deterministic replay certification and hash repeatability.
4. All 8 required negative invariants:
   - fixture cannot become live evidence
   - simulated cannot become actual
   - stale evidence cannot promote
   - failed execution cannot become unavailable
   - raw payloads cannot persist
   - secrets cannot persist
   - external workflow tools cannot become a second orchestrator
   - duplicate lineage or quality authorities are rejected
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from backend.observability.lineage_facets import (
    DatasetFacet,
    LineageSecurityError,
    RunFacet,
    attach_lineage_to_evidence,
    create_evidence_lineage,
)
from evaluation.quality_certification import (
    CANONICAL_QUALITY_AUTHORITY,
    DeterministicReplayCertifier,
    DuplicateAuthorityError,
    DuplicateOrchestratorError,
    ExpectationRule,
    ExpectationSuite,
    InvalidEvidencePromotionError,
    QualityAssertionState,
    SecretLeakError,
    StaleEvidenceError,
    UnredactedPayloadError,
)


def _get_base_evidence() -> dict:
    return {
        "product_id": "test-prod-100",
        "supplier_id": "supp-200",
        "name": "Organic Bamboo Toothbrush",
        "selling_price": 19.99,
        "unit_cost": 4.50,
        "shipping_cost": 2.00,
        "currency": "USD",
        "inventory_units": 50,
        "quality": {
            "provenance": "simulated",
            "attribution": "attributed",
            "completeness": "complete",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "source_ref": "fixture:test-feed:100",
        },
    }


def _get_standard_suite() -> ExpectationSuite:
    rules = (
        ExpectationRule("rule_exists", "product_id must exist", "product_id", "exists"),
        ExpectationRule("rule_name_non_empty", "name must be non-empty", "name", "non_empty"),
        ExpectationRule("rule_price_range", "price within range", "selling_price", "bounded_range", {"min_value": 1.0, "max_value": 1000.0}),
        ExpectationRule("rule_currency", "currency allowed", "currency", "allowed_set", {"allowed_values": ["USD", "EUR"]}),
    )
    return ExpectationSuite("test_contract_suite_v1", rules)


# -----------------------------------------------------------------------------
# Positive / Contract Tests
# -----------------------------------------------------------------------------

def test_lineage_facets_creation_and_serialization():
    inp = DatasetFacet("marketos.supplier", "quotes_raw", "sha_in_123", ("product_id", "unit_cost"), "static_fixture")
    out = DatasetFacet("marketos.evaluation", "product_scored", "sha_out_456", ("product_id", "score"), "simulated")

    facet = create_evidence_lineage(
        run_id="run-101",
        job_name="product_scoring",
        input_datasets=[inp],
        output_dataset=out,
        asset_key="product/opportunity/101",
        upstream_asset_keys=["supplier/quotes/raw"],
        asset_tags={"owner": "evaluation-ops", "tier": "planning"},
    )

    assert facet.run.run_id == "run-101"
    assert facet.run.orchestrator == "marketos_event_spine"
    assert len(facet.inputs) == 1
    assert facet.inputs[0].dataset_name == "quotes_raw"
    assert facet.asset is not None
    assert facet.asset.asset_key == "product/opportunity/101"
    assert facet.asset.upstream_asset_keys == ("supplier/quotes/raw",)

    d = facet.to_dict()
    assert d["lineage_id"] == facet.lineage_id
    assert d["run"]["job_name"] == "product_scoring"
    assert d["asset"]["tags"]["owner"] == "evaluation-ops"

    fingerprint1 = facet.fingerprint()
    fingerprint2 = facet.fingerprint()
    assert fingerprint1 == fingerprint2
    assert len(fingerprint1) == 64


def test_attach_lineage_to_evidence():
    evidence = _get_base_evidence()
    inp = DatasetFacet("marketos.supplier", "feed", "sha_in", ("product_id",), "static_fixture")
    out = DatasetFacet("marketos.evaluation", "evaluated", "sha_out", ("product_id",), "simulated")
    facet = create_evidence_lineage("run-102", "eval", [inp], out)

    attached = attach_lineage_to_evidence(evidence, facet)
    assert "lineage" in attached
    assert "lineage_fingerprint" in attached
    assert attached["lineage_fingerprint"] == facet.fingerprint()
    assert attached["product_id"] == "test-prod-100"


def test_expectation_suite_states():
    suite = _get_standard_suite()

    # 1. PASSED
    evidence = _get_base_evidence()
    state, results = suite.evaluate_record(evidence)
    assert state == QualityAssertionState.PASSED
    assert all(r.state == QualityAssertionState.PASSED for r in results)

    # 2. FAILED (price out of bounds)
    failing_evidence = dict(evidence, selling_price=0.50)
    state, results = suite.evaluate_record(failing_evidence)
    assert state == QualityAssertionState.FAILED
    assert any(r.state == QualityAssertionState.FAILED for r in results)

    # 3. UNAVAILABLE (optional missing field when not checking existence)
    partial_suite = ExpectationSuite("partial", (
        ExpectationRule("rule_opt", "optional check", "non_existent_field", "bounded_range", {"min_value": 0}),
    ))
    state, results = partial_suite.evaluate_record(evidence)
    assert state == QualityAssertionState.UNAVAILABLE
    assert results[0].state == QualityAssertionState.UNAVAILABLE

    # 4. DEFERRED (unknown rule type)
    deferred_suite = ExpectationSuite("deferred", (
        ExpectationRule("rule_def", "deferred rule", "product_id", "external_plugin_check"),
    ))
    state, results = deferred_suite.evaluate_record(evidence)
    assert state == QualityAssertionState.DEFERRED
    assert results[0].state == QualityAssertionState.DEFERRED


def test_deterministic_replay_consistency():
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()
    evidence = _get_base_evidence()

    report1 = certifier.certify(evidence, suite)
    report2 = certifier.certify(evidence, suite)
    report3 = certifier.certify(evidence, suite)

    assert report1.overall_state == QualityAssertionState.PASSED
    assert report1.replay_signature == report2.replay_signature
    assert report2.replay_signature == report3.replay_signature
    assert len(report1.replay_signature) == 64


# -----------------------------------------------------------------------------
# Required Negative Tests (8 Invariants)
# -----------------------------------------------------------------------------

def test_fixture_cannot_become_live_evidence():
    """Negative invariant 1: fixture/synthetic/mock cannot be promoted to live evidence."""
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()

    for forbidden_prov in ["mock", "fixture", "synthetic", "fallback", "unknown", "simulated"]:
        evidence = _get_base_evidence()
        evidence["quality"]["provenance"] = forbidden_prov
        with pytest.raises(InvalidEvidencePromotionError) as exc_info:
            certifier.certify(evidence, suite, target_provenance="live")
        assert "cannot be promoted to live evidence" in str(exc_info.value)


def test_simulated_cannot_become_actual():
    """Negative invariant 2: simulated evidence cannot become actual commercial evidence."""
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()

    for forbidden_prov in ["simulated", "mock", "fixture", "synthetic"]:
        evidence = _get_base_evidence()
        evidence["quality"]["provenance"] = forbidden_prov
        with pytest.raises(InvalidEvidencePromotionError) as exc_info:
            certifier.certify(evidence, suite, target_provenance="actual")
        assert "cannot be promoted to actual commercial evidence" in str(exc_info.value)


def test_stale_evidence_cannot_promote():
    """Negative invariant 3: evidence older than max_age_hours cannot promote."""
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()

    evidence = _get_base_evidence()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=72)
    evidence["quality"]["observed_at"] = stale_time.isoformat()

    with pytest.raises(StaleEvidenceError) as exc_info:
        certifier.certify(evidence, suite, target_provenance="promoted", max_age_hours=48.0)
    assert "exceeds max freshness window" in str(exc_info.value)


def test_failed_execution_cannot_become_unavailable():
    """Negative invariant 4: an expectation failure cannot be masked as UNAVAILABLE."""
    suite = ExpectationSuite("integrity_test", (
        ExpectationRule("rule_fail", "must fail", "selling_price", "bounded_range", {"min_value": 100.0}),
        ExpectationRule("rule_unavail", "unavailable field", "missing_dimension", "bounded_range", {"min_value": 0}),
    ))
    evidence = _get_base_evidence()  # selling_price = 19.99 (fails rule_fail)

    overall, results = suite.evaluate_record(evidence)
    assert any(r.state == QualityAssertionState.FAILED for r in results)
    assert any(r.state == QualityAssertionState.UNAVAILABLE for r in results)
    # Overall state MUST be FAILED, never UNAVAILABLE
    assert overall == QualityAssertionState.FAILED

    # Also test certifier verification
    certifier = DeterministicReplayCertifier()
    report = certifier.certify(evidence, suite)
    assert report.overall_state == QualityAssertionState.FAILED


def test_raw_payloads_cannot_persist():
    """Negative invariant 5: raw payloads and documents cannot persist in certified evidence."""
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()

    # Raw key in dictionary
    evidence1 = _get_base_evidence()
    evidence1["raw_html"] = "<html><body>raw page</body></html>"
    with pytest.raises(UnredactedPayloadError) as exc1:
        certifier.certify(evidence1, suite)
    assert "Forbidden raw payload" in str(exc1.value)

    # Raw HTML document string inside value
    evidence2 = _get_base_evidence()
    evidence2["notes"] = "<!DOCTYPE html><html><body>dump</body></html>"
    with pytest.raises(UnredactedPayloadError) as exc2:
        certifier.certify(evidence2, suite)
    assert "Raw HTML document content detected" in str(exc2.value)


def test_secrets_cannot_persist():
    """Negative invariant 6: secrets cannot persist in evidence records or lineage metadata."""
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()

    # In evidence
    evidence = _get_base_evidence()
    evidence["token"] = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    with pytest.raises(SecretLeakError) as exc_info:
        certifier.certify(evidence, suite)
    assert "Secret-shaped credential pattern detected" in str(exc_info.value)

    # In lineage facet
    inp = DatasetFacet("marketos.supplier", "feed", "sha_in", ("id",), "static_fixture")
    out = DatasetFacet("marketos.evaluation", "eval", "sha_out", ("id",), "simulated")
    with pytest.raises(LineageSecurityError) as exc_facet:
        create_evidence_lineage(
            "run-sec", "job", [inp], out,
            asset_tags={"key": "sk-live-1234567890abcdefghijklmn"}
        )
    assert "Secret-shaped credential pattern detected" in str(exc_facet.value)


def test_external_workflow_tools_cannot_become_second_orchestrator():
    """Negative invariant 7: external engines (Temporal, Prefect, Airbyte, n8n) cannot be claimed as orchestrator."""
    certifier = DeterministicReplayCertifier()
    suite = _get_standard_suite()

    for engine in ["temporal", "prefect", "airbyte", "n8n", "celery", "airflow"]:
        evidence = _get_base_evidence()
        evidence["orchestrator"] = engine
        with pytest.raises(DuplicateOrchestratorError) as exc_info:
            certifier.certify(evidence, suite)
        assert "External orchestrator" in str(exc_info.value)

    # In RunFacet directly
    with pytest.raises(LineageSecurityError) as exc_rf:
        RunFacet(run_id="r1", job_name="j1", orchestrator="temporal")
    assert "singular marketos_event_spine" in str(exc_rf.value)


def test_duplicate_lineage_or_quality_authorities_rejected():
    """Negative invariant 8: duplicate quality/lineage authorities are rejected fail-closed."""
    with pytest.raises(DuplicateAuthorityError) as exc_info:
        DeterministicReplayCertifier(authority="external_vendor_quality_gate")
    assert "duplicate authority rejected fail-closed" in str(exc_info.value)

    # Canonical passes
    cert = DeterministicReplayCertifier(authority=CANONICAL_QUALITY_AUTHORITY)
    assert cert.authority == CANONICAL_QUALITY_AUTHORITY


def test_quality_certification_evaluation_package_accessible():
    """Verify quality certification primitives are cleanly exported from the evaluation root."""
    import evaluation

    assert hasattr(evaluation, "DeterministicReplayCertifier")
    assert hasattr(evaluation, "QualityAssertionState")
    assert hasattr(evaluation, "QualityAssertionResult")
    assert hasattr(evaluation, "ExpectationSuite")
    assert hasattr(evaluation, "ExpectationRule")
    assert hasattr(evaluation, "ReplayCertificationReport")
    assert hasattr(evaluation, "CANONICAL_QUALITY_AUTHORITY")
    assert hasattr(evaluation, "certify_data_quality")
    assert hasattr(evaluation, "quality_reasons")
    assert hasattr(evaluation, "deduplicate_observations")

    certifier = evaluation.DeterministicReplayCertifier()
    assert certifier.authority == evaluation.CANONICAL_QUALITY_AUTHORITY


def test_canonical_quality_authority_consolidation():
    """Verify evaluation.quality is the canonical authority and quality_certification is a thin adapter."""
    import evaluation.quality as eq
    import evaluation.quality_certification as eqc

    # Assert exact reference identity across the canonical module and adapter
    assert eq.DeterministicReplayCertifier is eqc.DeterministicReplayCertifier
    assert eq.QualityAssertionState is eqc.QualityAssertionState
    assert eq.ExpectationSuite is eqc.ExpectationSuite
    assert eq.ExpectationRule is eqc.ExpectationRule
    assert eq.CANONICAL_QUALITY_AUTHORITY is eqc.CANONICAL_QUALITY_AUTHORITY

    # Base quality functions remain available on canonical authority
    assert hasattr(eq, "quality_reasons")
    assert hasattr(eq, "deduplicate_observations")
    assert hasattr(eq, "certify_data_quality")


def test_data_quality_contract_certification_bridge():
    """Verify DataQuality contract directly bridges into deterministic replay certification."""
    from evaluation.contracts import DataQuality
    from evaluation.quality import certify_data_quality, QualityAssertionState

    # Normal valid simulated data quality record
    dq = DataQuality(
        provenance="simulated",
        attribution="attributed",
        completeness="complete",
        observed_at=datetime.now(timezone.utc),
        source_ref="fixture://product/123",
    )
    report = certify_data_quality(dq)
    assert report.overall_state == QualityAssertionState.PASSED
    assert len(report.replay_signature) == 64
    assert len(report.record_fingerprint) == 64


def test_stale_and_conflicting_data_quality_promotion_blocked():
    """Verify DataQuality records fail closed on stale timestamps or illegal promotion."""
    from evaluation.contracts import DataQuality
    from evaluation.quality import (
        certify_data_quality,
        InvalidEvidencePromotionError,
        StaleEvidenceError,
    )

    # 1. Illegal promotion from simulated to live
    dq_sim = DataQuality(
        provenance="simulated",
        attribution="attributed",
        completeness="complete",
        observed_at=datetime.now(timezone.utc),
    )
    with pytest.raises(InvalidEvidencePromotionError) as exc_p:
        certify_data_quality(dq_sim, target_provenance="live")
    assert "cannot be promoted to live evidence" in str(exc_p.value)

    # 2. Stale evidence promotion rejected
    dq_stale = DataQuality(
        provenance="live",
        attribution="attributed",
        completeness="complete",
        observed_at=datetime.now(timezone.utc) - timedelta(hours=50),
    )
    with pytest.raises(StaleEvidenceError) as exc_s:
        certify_data_quality(dq_stale, target_provenance="live")
    assert "exceeds max freshness window" in str(exc_s.value)


def test_trustos_and_local_gate_state_compatibility():
    """Verify bidirectional state mappings across QualityAssertionState, TrustOS, and local gates."""
    from evaluation.quality import (
        QualityAssertionState,
        quality_state_to_trustos_evidence_status,
        trustos_evidence_status_to_quality_state,
        quality_state_to_local_gate_class,
    )

    assert quality_state_to_trustos_evidence_status(QualityAssertionState.PASSED) == "passed"
    assert quality_state_to_trustos_evidence_status(QualityAssertionState.FAILED) == "failed"
    assert quality_state_to_trustos_evidence_status(QualityAssertionState.UNAVAILABLE) == "requires_review"
    assert quality_state_to_trustos_evidence_status(QualityAssertionState.DEFERRED) == "draft"

    assert trustos_evidence_status_to_quality_state("passed") == QualityAssertionState.PASSED
    assert trustos_evidence_status_to_quality_state("failed") == QualityAssertionState.FAILED
    assert trustos_evidence_status_to_quality_state("draft") == QualityAssertionState.DEFERRED
    assert trustos_evidence_status_to_quality_state("stale") == QualityAssertionState.UNAVAILABLE

    assert quality_state_to_local_gate_class(QualityAssertionState.PASSED) == "pass"
    assert quality_state_to_local_gate_class(QualityAssertionState.FAILED) == "changed_scope_failure"
    assert quality_state_to_local_gate_class(QualityAssertionState.UNAVAILABLE) == "unavailable_dependency"
    assert quality_state_to_local_gate_class(QualityAssertionState.DEFERRED) == "not_run"


def test_lineage_trust_evidence_record_integration():
    """Verify lineage facets wire directly into canonical TrustOS TrustEvidenceRecord."""
    from backend.observability.lineage_facets import (
        DatasetFacet,
        create_evidence_lineage,
        create_trust_evidence_with_lineage,
    )

    inp = DatasetFacet("marketos.supplier", "quotes_raw", "sha_in", ("product_id",), "static_fixture")
    out = DatasetFacet("marketos.evaluation", "product_scored", "sha_out", ("product_id",), "simulated")
    facet = create_evidence_lineage("run-777", "scoring", [inp], out)

    evidence_record = create_trust_evidence_with_lineage(
        facet,
        control_id="SEC-L1-LINEAGE-01",
        summary="Automated pipeline lineage proof",
    )

    assert evidence_record.evidence_id == f"evidence-lineage-{facet.lineage_id}"
    assert evidence_record.control_id == "SEC-L1-LINEAGE-01"
    assert evidence_record.status == "passed"
    assert f"trustos://lineage/{facet.lineage_id}" in evidence_record.source_ref
    assert evidence_record.internal_only is True


def test_lineage_data_quality_and_report_projection_integration():
    """Verify lineage facets attach cleanly to DataQuality records and format for report projections."""
    from backend.observability.lineage_facets import (
        DatasetFacet,
        create_evidence_lineage,
        attach_lineage_to_data_quality,
        format_lineage_for_report,
    )
    from evaluation.contracts import DataQuality

    inp = DatasetFacet("marketos.signals", "signals_raw", "sha_sig", ("signal_id",), "static_fixture")
    out = DatasetFacet("marketos.candidates", "candidates_norm", "sha_cand", ("candidate_id",), "simulated")
    facet = create_evidence_lineage("run-888", "candidate_norm", [inp], out, asset_key="candidates/norm")

    # Wire to DataQuality
    base_dq = DataQuality(provenance="simulated", attribution="attributed")
    enriched_dq = attach_lineage_to_data_quality(base_dq, facet)
    assert f"lineage://{facet.lineage_id}" in enriched_dq.source_ref

    # Format for report projections
    report_summary = format_lineage_for_report(facet)
    assert report_summary["lineage_id"] == facet.lineage_id
    assert report_summary["job_name"] == "candidate_norm"
    assert report_summary["orchestrator"] == "marketos_event_spine"
    assert report_summary["input_dataset_count"] == 1
    assert report_summary["has_asset_metadata"] is True
