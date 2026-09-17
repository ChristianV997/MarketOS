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
